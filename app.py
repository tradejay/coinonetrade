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

# 잔고 정보 업데이트 및 표시 함수
def update_balance_info():
    balances = st.session_state.balances
    krw_balance = balances.get('krw', {})
    usdt_balance = balances.get('usdt', {})
    
    available_krw = float(krw_balance.get('available', '0'))
    limit_krw = float(krw_balance.get('limit', '0'))
    total_krw = available_krw + limit_krw
    
    available_usdt = float(usdt_balance.get('available', '0'))
    limit_usdt = float(usdt_balance.get('limit', '0'))
    total_usdt = available_usdt + limit_usdt

    st.markdown("""
    ### 계좌 잔고
    | 화폐 | 보유 | 주문 가능 |
    |:-----|-----:|----------:|
    | KRW  | {:,.0f} | {:,.0f} |
    | USDT | {:,.2f} | {:,.2f} |
    """.format(total_krw, available_krw, total_usdt, available_usdt))

# Streamlit UI 설정
st.set_page_config(layout="wide")

# 초기 세션 상태 설정
if 'orderbook' not in st.session_state:
    st.session_state.orderbook = fetch_order_book()

# 업데이트 호출
update_data()

# 잔고 정보 표시
update_balance_info()

# 스타일 설정
st.markdown("""
<style>
    .reportview-container .main .block-container {
        padding-top: 1rem;
        padding-right: 1rem;
        padding-left: 1rem;
        padding-bottom: 1rem;
        max-width: 100%;
    }
    .stButton > button {
        width: 100%;
        padding: 0.1rem 0.1rem;
        font-size: 0.6rem;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        opacity: 0.9;
    }
    .stTextInput > div > div > input {
        font-size: 0.7rem;
    }
    .small-font {
        font-size: 0.7rem;
    }
    .stSelectbox {
        font-size: 0.7rem;
    }
    .stSlider {
        width: 180px;
    }
    .ask-button {
        background-color: #ff4b4b !important;
        color: white !important;
        font-size: 0.6rem !important;
        padding: 2px 5px !important;
        margin: 2px 0 !important;
    }
    .ask-button:hover {
        opacity: 0.8;
    }
    .cancel-button {
        background-color: #ff9800 !important;
        color: white !important;
        font-size: 0.6rem !important;
        padding: 2px 5px !important;
    }
</style>
""", unsafe_allow_html=True)

# 메인 페이지 내용
# st.title("Coinone 매도 Tool", anchor=False)

# 주문 창
col_left, col_right = st.columns([1, 1])

with col_right:
    # st.markdown("<div class='order-box'>", unsafe_allow_html=True)
    # # st.subheader("매도 주문", anchor=False)
    
    order_type_display = st.selectbox("주문 유형", ["지정가"], key='order_type')
    order_type = "LIMIT" if order_type_display == "지정가" else "MARKET" if order_type_display == "시장가" else "STOP_LIMIT"

    side = "SELL"

    if order_type != "MARKET":
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown("<div style='font-size: 1.1em; margin-bottom: 0.5em;'>매도 호가</div>", unsafe_allow_html=True)
    order_type = "LIMIT" if order_type_display == "지정가" else "MARKET" if order_type_display == "시장가" else "STOP_LIMIT"

    side_display = "매도"
    side = "SELL"

    if order_type != "MARKET":
        col1, col2 = st.columns([1, 2])
        with col1:
            # st.markdown("### 매도 호가")
            bids_df, asks_df = st.session_state.orderbook
            if asks_df is not None:
                for i, ask in asks_df.iterrows():
                    if st.button(f"{ask['price']:,.0f}", key=f"ask_btn_{i}", help="클릭하여 가격 선택"):
                        st.session_state.selected_price = f"{ask['price']:,.0f}"
            
            # 호가 정보 업데이트 버튼 추가
            if st.button("호가 정보 업데이트", key="update_orderbook"):
                st.session_state.orderbook = fetch_order_book()
                st.success("호가 정보가 업데이트되었습니다.")
        
        with col2:
            price_display = st.text_input("가격 (KRW)", st.session_state.get('selected_price', ''), key='price')
            # 쉼표를 제거하고 숫자만 추출
            price = price_display.replace(',', '') if price_display else None
    else:
        price = None

    percentage = st.slider("매도 비율 (%)", min_value=0, max_value=100, value=0, step=1, key='percentage')

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
                    available_usdt = float(st.session_state.balances.get('usdt', {}).get('available', '0'))
                    if side == "BUY":
                        available_krw = float(st.session_state.balances.get('krw', {}).get('available', '0'))
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
        
        st.markdown("<div class='small-font'>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            quantity_input = st.text_input("수량 (USDT)", value=f"{float(quantity):,.4f}", disabled=True)
        with col2:
            st.write(f"환산 금액: {krw_equivalent:,.2f} KRW")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        quantity = st.text_input("수량 (USDT)", value="0")

    if st.button(f"{side_display} 주문하기", key="place_order", help="클릭하여 주문 실행"):
        # 쉼표가 제거된 price 값을 사용
        place_order(order_type, side, price, quantity)

    st.markdown("</div>", unsafe_allow_html=True)

    # 미체결 주문 관련 기능 추가
    st.markdown("### 매도 미체결 주문")
    orders = fetch_active_orders()
    sell_orders = [order for order in orders if order['side'] == 'SELL']
    
    if sell_orders:
        for order in sell_orders:
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.write(f"종목: {order['target_currency']}")
            col2.write(f"유형: {order['type']}")
            col3.write(f"가격: {float(order['price']):,.2f}")
            col4.write(f"수량: {float(order['remain_qty']):,.4f}")
            if col5.button(f"취소", key=f"cancel_{order['order_id']}", help="클릭하여 주문 취소"):
                cancel_order(order['order_id'])
                st.rerun()
    else:
        st.info("매도 미체결 주문 없음")
