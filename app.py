import streamlit as st
import requests
import pandas as pd
import json
import uuid
import base64
import hashlib
import hmac
import httplib2
import time

# 사용자 정보 (토큰 및 키) - secrets.toml에서 가져오기
ACCESS_TOKEN = st.secrets.get("access_key", "")
SECRET_KEY = bytes(st.secrets.get("private_key", ""), 'utf-8')

def get_encoded_payload(payload):
    payload['nonce'] = str(uuid.uuid4())  # nonce 추가
    dumped_json = json.dumps(payload)
    encoded_json = base64.b64encode(dumped_json.encode('utf-8'))  # UTF-8 인코딩 추가
    return encoded_json.decode('utf-8')  # 결과를 문자열로 디코딩

def get_signature(encoded_payload):
    signature = hmac.new(SECRET_KEY, encoded_payload.encode('utf-8'), hashlib.sha512)  # encoded_payload 인코딩
    return signature.hexdigest()

def get_response(action, payload):
    url = f'https://api.coinone.co.kr{action}'
    encoded_payload = get_encoded_payload(payload)
    headers = {
        'Content-type': 'application/json',
        'X-COINONE-PAYLOAD': encoded_payload,
        'X-COINONE-SIGNATURE': get_signature(encoded_payload),
    }

    http = httplib2.Http()
    response, content = http.request(url, 'POST', body=encoded_payload, headers=headers)

    print(f"HTTP Status Code: {response.status}")
    print(f"Response Content: {content.decode('utf-8')}")

    try:
        json_content = json.loads(content.decode('utf-8'))
        if response.status == 200 and json_content.get('result') == 'success':
            return json_content
        else:
            error_code = json_content.get('error_code', 'Unknown error code')
            error_msg = json_content.get('error_msg', 'Unknown error message')
            st.error(f"API 요청 오류: 코드 {error_code}, 메시지: {error_msg}")
            return None
    except json.JSONDecodeError as e:
        st.error(f"JSONDecodeError: {e}")
        st.error(f"Response content: {content.decode('utf-8')}")
        return None

# 호가 조회 함수
def fetch_order_book():
    url = "https://api.coinone.co.kr/public/v2/orderbook/KRW/USDT?size=5"
    headers = {"accept": "application/json"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        if data.get('result') == 'success':
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            bids_df = pd.DataFrame(bids)
            asks_df = pd.DataFrame(asks)

            bids_df['price'] = pd.to_numeric(bids_df['price'])
            bids_df['qty'] = pd.to_numeric(bids_df['qty'])
            asks_df['price'] = pd.to_numeric(asks_df['price'])
            asks_df['qty'] = pd.to_numeric(asks_df['qty'])

            asks_df = asks_df.iloc[::-1]  # 매도 호가 역순 정렬
            return bids_df.head(5), asks_df.head(5)  # 상위 5개만 표시
        else:
            st.error(f"API returned an error: {data.get('error_code', 'Unknown error')}")
    else:
        st.error(f"Failed to fetch data from API. Status code: {response.status_code}")
    return None, None

# 전체 잔고 조회 함수
def fetch_balances():
    action = '/v2.1/account/balance/all'
    payload = {'access_token': ACCESS_TOKEN}
    result = get_response(action, payload)

    if result:
        balances = result.get('balances', [])
        filtered_balances = {}
        for balance in balances:
            currency = balance.get('currency', '').lower()
            if currency in ['krw', 'usdt']:
                filtered_balances[currency] = balance
        return filtered_balances
    else:
        st.error("잔고 조회 오류 발생")
        return {}

# 매수/매도 주문 함수
def place_order(order_type, side, price=None, quantity=None):
    action = "/v2.1/order"
    payload = {
        "access_token": ACCESS_TOKEN,
        "nonce": str(uuid.uuid4()),
        "side": side,
        "quote_currency": "KRW",
        "target_currency": "USDT",
        "type": order_type,
    }

    # 최소 주문 기준 설정
    MIN_ORDER_AMOUNT_KRW = 1000  # 예시로 설정한 최소 금액 (KRW)
    MIN_ORDER_QTY_USDT = 0.001  # 예시로 설정한 최소 수량 (USDT)

    # 수량 검증 및 변환
    if quantity is None or str(quantity).strip() == '':
        st.error("수량이 입력되지 않았습니다. 유효한 수량을 입력해주세요.")
        return

    try:
        # 수량을 안전하게 float으로 변환
        quantity_value = float(quantity)

        # LIMIT 주문인 경우
        if order_type == "LIMIT" and price:
            price_value = float(price)
            
            if price_value <= 0 or quantity_value <= 0:
                st.error("가격 및 수량은 0보다 커야 합니다.")
                return
            
            # 최소 주문 금액 기준 확인
            if price_value * quantity_value < MIN_ORDER_AMOUNT_KRW:
                st.error(f"주문 금액이 최소 금액 {MIN_ORDER_AMOUNT_KRW} KRW보다 작습니다.")
                return

            # 가격 및 수량 포맷팅: 소수점 자리수 조정
            payload["price"] = f"{price_value:.2f}"  # 가격을 소수점 2자리로 처리
            payload["qty"] = f"{quantity_value:.4f}"  # 수량을 소수점 4자리로 처리
            payload["post_only"] = True  # 지정가 주문일 때, post_only 옵션 추가

        # MARKET 주문인 경우
        elif order_type == "MARKET":
            if quantity_value <= 0:
                st.error("매수 금액/매도 수량은 0보다 커야 합니다.")
                return
            
            # 시장가 매수 시 최소 금액 확인
            if side == "BUY":
                if quantity_value < MIN_ORDER_AMOUNT_KRW:
                    st.error(f"주문 금액이 최소 금액 {MIN_ORDER_AMOUNT_KRW} KRW보다 작습니다.")
                    return
                payload["amount"] = f"{quantity_value:.2f}"  # 시장가 매수 시 amount 사용, 소수점 2자리 제한
            
            # 시장가 매도 시 최소 수량 확인
            else:
                if quantity_value < MIN_ORDER_QTY_USDT:
                    st.error(f"주문 수량이 최소 수량 {MIN_ORDER_QTY_USDT} USDT보다 작습니다.")
                    return
                payload["qty"] = f"{quantity_value:.4f}"  # 시장가 매도 시 qty 사용, 소수점 4자리 제한

    except ValueError as e:
        st.error(f"가격 또는 수량 입력이 잘못되었습니다: {e}")
        return

    # API 요청 및 결과 처리
    result = get_response(action, payload)

    if result:
        st.success(f"{side} 주문이 성공적으로 접수되었습니다. 주문 ID: {result.get('order_id')}")
    else:
        st.error("주문 오류 발생")

# 미체결 주문 조회 함수
def fetch_active_orders():
    action = "/v2.1/order/active_orders"
    payload = {
        "access_token": ACCESS_TOKEN,
        "nonce": str(uuid.uuid4()),
        "quote_currency": "KRW",
        "target_currency": "USDT"
    }

    result = get_response(action, payload)

    if result:
        return result.get('active_orders', [])
    else:
        st.error("미체결 주문 조회 오류 발생")
        return []

# 주문 취소 함수
def cancel_order(order_id):
    action = "/v2.1/order/cancel"
    payload = {
        "access_token": ACCESS_TOKEN,
        "nonce": str(uuid.uuid4()),
        "order_id": order_id,
        "quote_currency": "KRW",
        "target_currency": "USDT"
    }

    result = get_response(action, payload)

    if result:
        st.success(f"주문이 성공적으로 취소되었습니다. 주문 ID: {order_id}")
    else:
        st.error("주문 취소 오류 발생")

# 자동으로 잔고와 주문내역 업데이트 함수
def update_data():
    if st.session_state.get('last_update_time', 0) < time.time() - 1:
        st.session_state.balances = fetch_balances()
        st.session_state.orders = fetch_active_orders()
        st.session_state.orderbook = fetch_order_book()
        st.session_state.last_update_time = time.time()

# Streamlit UI 설정
st.title("Coinone 종합 거래 도구")

# 초기 세션 상태 설정
if 'selected_price' not in st.session_state:
    st.session_state['selected_price'] = ""

# 잔고와 주문 내역 초기화
if 'balances' not in st.session_state:
    st.session_state.balances = fetch_balances()
if 'orders' not in st.session_state:
    st.session_state.orders = fetch_active_orders()
if 'orderbook' not in st.session_state:
    st.session_state.orderbook = fetch_order_book()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = 0

# 업데이트 호출
update_data()

# 잔고 정보
balances = st.session_state.balances
available_krw = float(balances.get('krw', {}).get('available', '0'))
available_usdt = float(balances.get('usdt', {}).get('available', '0'))

# 레이아웃 설정
col1, col2 = st.columns([2, 2])

with col1:
    # 호가 조회
    bids_df, asks_df = st.session_state.orderbook

    # 매도 호가
    st.subheader('매도 호가 (Asks)')
    col_ask_click, col_ask_window = st.columns([1, 2])
    with col_ask_click:
        if asks_df is not None:
            st.write("**호가 클릭.**")
            for index, row in asks_df.iterrows():
                if st.button(f"{row['price']}", key=f"ask_{index}"):
                    st.session_state['selected_price'] = str(row['price'])
    with col_ask_window:
        if asks_df is not None:
            st.dataframe(asks_df)

    # 매수 호가
    st.subheader('매수 호가 (Bids)')
    col_bid_click, col_bid_window = st.columns([1, 2])
    with col_bid_click:
        if bids_df is not None:
            st.write("**호가 클릭.**")
            for index, row in bids_df.iterrows():
                if st.button(f"{row['price']}", key=f"bid_{index}"):
                    st.session_state['selected_price'] = str(row['price'])
    with col_bid_window:
        if bids_df is not None:
            st.dataframe(bids_df)

with col2:
    st.subheader("계좌 잔고")
    if balances:
        for currency, balance in balances.items():
            available = float(balance.get('available', '0'))
            st.write(f"{currency.upper()}: {available:,.2f}")
    else:
        st.write("잔고 정보를 불러올 수 없습니다.")

    # 'KRW' 정보 찾기
    krw_balance = balances.get('krw', None)

    if krw_balance:  # 'KRW' 정보가 존재하는 경우
        available_krw = float(krw_balance.get('available', '0'))
        limit_krw = float(krw_balance.get('limit', '0'))
        total_krw = available_krw + limit_krw

        with st.container():
            st.subheader("잔고 정보")
            st.write(f"보유 KRW: {total_krw:.1f} 원") 
            st.write(f"가용 KRW: {available_krw:.1f} 원") 
            st.write(f"주문 가능한 KRW: {max(0, available_krw - limit_krw):.1f} 원") 

    else:  # 'KRW' 정보가 없는 경우
        with st.container():
            st.subheader("잔고 정보")
            st.write("KRW 잔고 정보를 찾을 수 없습니다.")

# 주문 창
with st.container():
    st.subheader("매수/매도 주문")
    order_type_display = st.selectbox("주문 유형 선택", ["지정가", "시장가", "예약가"])
    order_type = "LIMIT" if order_type_display == "지정가" else "MARKET" if order_type_display == "시장가" else "STOP_LIMIT"

    # 주문 방향 선택
    side_display = st.radio("주문 방향 선택", ["매수", "매도"])
    side = "BUY" if side_display == "매수" else "SELL"

    # 지정가 입력 필드에 클릭된 가격 반영
    price = st.text_input("가격 (KRW)", st.session_state['selected_price'], key='price') if order_type != "MARKET" else None

    # Percentage slider
    percentage = st.slider("사용할 자금의 비율 (%)", min_value=0, max_value=100, value=0, step=1)

    # Calculate quantity based on percentage and price
    quantity = '0'
    krw_equivalent = 0  # KRW로 환산된 금액
    if percentage > 0:
        try:
            if order_type != "MARKET" and (price is None or price == ''):
                st.warning("가격을 입력해주세요.")
            else:
                price_value = float(price) if price else 0
                if price_value <= 0:
                    st.warning("가격은 0보다 커야 합니다.")
                else:
                    if side == "BUY":
                        amount_krw = available_krw * (percentage / 100)
                        quantity_value = amount_krw / price_value
                        quantity = f"{quantity_value:.4f}"  # 수량을 소수점 4자리로 포맷
                        krw_equivalent = amount_krw
                    else:
                        amount_usdt = available_usdt * (percentage / 100)
                        quantity_value = amount_usdt
                        quantity = f"{quantity_value:.4f}"  # 수량을 소수점 4자리로 포맷
                        krw_equivalent = float(quantity) * price_value
        except ValueError:
            st.warning("유효한 가격을 입력해주세요.")
        quantity_input = st.text_input("수량 (USDT)", value=quantity, disabled=True)
        st.write(f"환산 금액: {krw_equivalent:.2f} KRW")
    else:
        quantity = st.text_input("수량 (USDT)", value="0")

    if st.button(f"{side_display} 주문하기"):
        # place_order 호출 시 수량을 float으로 변환해서 전달
        place_order(order_type, side, price, quantity)

# 주문 현황
with st.container():
    st.subheader("미체결 주문 조회 및 취소")
    orders = st.session_state.orders
    if orders:
        st.write("### 미체결 주문 목록")
        for order in orders:
            col1_order, col2_order, col3_order, col4_order = st.columns(4)
            col1_order.write(f"종목: {order['target_currency']}")
            col2_order.write(f"유형: {order['type']}")
            col3_order.write(f"가격: {order['price']}")
            col4_order.write(f"수량: {order['remain_qty']}")
            if st.button(f"주문 취소 ({order['order_id']})", key=f"cancel_{order['order_id']}"):
                cancel_order(order['order_id'])
    else:
        st.info("현재 미체결 주문이 없습니다.")
