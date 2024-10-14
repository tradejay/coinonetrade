import streamlit as st
import uuid  # 파일 상단에 이 줄을 추가해주세요


# Streamlit UI 설정
st.set_page_config(layout="wide")

from datetime import datetime, timedelta

import requests
import pandas as pd
import json
import uuid
import base64
import hashlib
import hmac
import httplib2
import time
import math
import json
import os
from datetime import datetime
from git import Repo

# Git 저장소 설정
REPO_PATH = '.'  # 현재 디렉토리를 저장소로 사용
LOG_FILE = 'order_logs.json'

def init_git_repo():
    if not os.path.exists(os.path.join(REPO_PATH, '.git')):
        repo = Repo.init(REPO_PATH)
        # 초기 커밋 생성
        open(os.path.join(REPO_PATH, LOG_FILE), 'a').close()  # 빈 로그 파일 생성
        repo.index.add([LOG_FILE])
        repo.index.commit("Initial commit with empty log file")
    else:
        repo = Repo(REPO_PATH)
    return repo

repo = init_git_repo()

def load_order_log():
    try:
        with open(os.path.join(REPO_PATH, LOG_FILE), 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_order_log(log_data):
    logs = load_order_log()
    logs.append(log_data)
    logs = logs[-100:]  # 최근 100개의 로그만 유지
    
    with open(os.path.join(REPO_PATH, LOG_FILE), 'w') as f:
        json.dump(logs, f, indent=2)
    
    repo.index.add([LOG_FILE])
    repo.index.commit(f"Update log: {datetime.now().isoformat()}")

# 사용자 정보 (토큰 및 키) - secrets.toml에서 가져오기
ACCESS_TOKEN = st.secrets.get("access_key", "")
SECRET_KEY = bytes(st.secrets.get("private_key", ""), 'utf-8')

# # 로컬 환경에서 secrets.toml 파일 로드 (이 부분은 Streamlit Cloud에서는 실행되지 않음)
# if not os.getenv('STREAMLIT_SERVER_URL'):  # Streamlit Cloud에서 실행 중이 아닐 때
#     try:
#         from dotenv import load_dotenv
#         load_dotenv('.streamlit/secrets.toml')
#         ACCESS_TOKEN = os.getenv("access_key", "")
#         SECRET_KEY = bytes(os.getenv("private_key", ""), 'utf-8')
#     except ImportError:
#         st.warning("dotenv 모듈을 찾을 수 없습니다. 로컬 환경에서 실행 중이라면 'pip install python-dotenv'를 실행하세요.")

def fetch_order_detail(order_id):
    action = "/v2.1/order/detail"
    payload = {
        "access_token": ACCESS_TOKEN,
        "nonce": str(uuid.uuid4()),
        "order_id": order_id,
        "quote_currency": "KRW",
        "target_currency": "USDT"
    }

    result = get_response(action, payload)

    if result and result.get('result') == 'success':
        return result.get('order')
    else:
        st.error("주문 조회 오류 발생")
        return None

    
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
    try:
        json_content = json.loads(content.decode('utf-8'))
        if 'balances' in json_content:
            filtered_balances = [balance for balance in json_content['balances'] if balance['currency'] in ['KRW', 'USDT']]
            json_content['balances'] = filtered_balances
        
        print(f"Filtered Response Content: {json.dumps(json_content, indent=2)}")
        return json_content
    except json.JSONDecodeError:
        print(f"Response Content (raw): {content.decode('utf-8')}")
        return None

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
    

def save_log(log_data):
    try:
        save_order_log(log_data)
        st.success("로그가 성공적으로 저장되었습니다.")
        
        # 로그 표시
        st.markdown("### 최근 주문 로그")
        st.write(f"시간: {log_data['timestamp']}")
        st.write(f"주문 유형: {log_data['order_type']}")
        st.write(f"매수/매도: {log_data['side']}")
        st.write(f"가격: {log_data['price']}")
        st.write(f"수량: {log_data['quantity']}")
        st.write(f"상태: {log_data['status']}")
        st.write("---")
        
    except Exception as e:
        st.error(f"로그 저장 중 오류 발생: {str(e)}")


        

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
                filtered_balances[currency] = {
                    'available': float(balance.get('available', '0')),
                    'limit': float(balance.get('limit', '0')),
                    'total': float(balance.get('available', '0')) + float(balance.get('limit', '0'))
                }
        return filtered_balances
    else:
        st.error("잔고 조회 오류 발생")
        return {}

# 매수/매도 주문 함수
def place_order(order_type, side, price, quantity):
    action = "/v2.1/order"
    order_uuid = str(uuid.uuid4())
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "uuid": order_uuid,
        "order_type": order_type,
        "side": side,
        "price": price,
        "quantity": quantity,
        "status": "initiated"
    }

    try:
        payload = {
            "access_token": ACCESS_TOKEN,
            "nonce": order_uuid,
            "side": side,
            "quote_currency": "KRW",
            "target_currency": "USDT",
            "type": order_type,
            "price": f"{float(price):.2f}",
            "qty": f"{float(quantity):.4f}",
            "post_only": False  # 이 줄을 추가합니다
        }

        # 최소 주문 기준 설정
        MIN_ORDER_AMOUNT_KRW = 1000
        MIN_ORDER_QTY_USDT = 0.001

        price_value = float(price)
        quantity_value = float(quantity)

        if price_value <= 0 or quantity_value <= 0:
            raise ValueError("가격 및 수량은 0보다 커야 합니다.")
        
        if price_value * quantity_value < MIN_ORDER_AMOUNT_KRW:
            raise ValueError(f"주문 금액이 최소 금액 {MIN_ORDER_AMOUNT_KRW} KRW보다 작습니다.")

        if quantity_value < MIN_ORDER_QTY_USDT:
            raise ValueError(f"주문 수량이 최소 수량 {MIN_ORDER_QTY_USDT} USDT보다 작습니다.")

        result = get_response(action, payload)

        if result and result.get('result') == 'success':
            order_id = result.get('order_id')
            st.success(f"{side} 주문이 성공적으로 접수되었습니다. 주문 ID: {order_id}")
            log_data["status"] = "success"
            log_data["order_id"] = order_id
            log_data["response"] = result
            
            # 여기서 로그를 저장하고 Git에 커밋
            save_order_log(log_data)
            
            if 'order_tracking' not in st.session_state:
                st.session_state.order_tracking = {}
            st.session_state.order_tracking[order_uuid] = {
                'order_id': order_id,
                'status': 'pending',
                'side': side,
                'type': order_type,
                'price': price,
                'quantity': quantity
            }
            
            st.session_state.orders = fetch_active_orders()
            st.rerun()
        else:
            st.error("주문 오류 발생")
            log_data["status"] = "api_error"
            log_data["error_message"] = "API 응답 실패"
            # 에러 로그도 저장하고 Git에 커밋
            save_order_log(log_data)

    except ValueError as e:
        st.error(f"입력 오류: {e}")
        log_data["status"] = "input_error"
        log_data["error_message"] = str(e)
        # 에러 로그도 저장하고 Git에 커밋
        save_order_log(log_data)
    except Exception as e:
        st.error(f"주문 처리 중 오류 발생: {e}")
        log_data["status"] = "processing_error"
        log_data["error_message"] = str(e)
        # 에러 로그도 저장하고 Git에 커밋
        save_order_log(log_data)

    return log_data["status"] == "success"


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
    if st.session_state.get('last_update_time', 0) < time.time() - 0.5:
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
        background-color: #4CAF50 !important;  /* 약간 옅은 초록색 배경 */
        color: white !important;  /* 흰색 글자 */
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        opacity: 0.9;  /* 호버 시 약간 투명해지는 효과 */
    }
    .stTextInput > div > div > input {
        font-size: 0.7rem;
    }
    .sidebar .sidebar-content {
        width: 200px;
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
    
    .buy-button {
        background-color: #ff4b4b !important;
        color: white !important;
    }
    .sell-button {
        background-color: #4b4bff !important;  /* 파란색 배경 */
        color: white !important;  /* 흰색 글자 */
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
    .stRadio [role=radiogroup] {
        flex-direction: row;
        justify-content: space-between;
    }
    .stRadio [role=radiogroup] label {
        width: 50%;
        padding: 10px;
        text-align: center;
        transition: all 0.3s ease;
    }
    .stRadio [role=radiogroup] label:first-child {
        text-align: left;
    }
    .stRadio [role=radiogroup] label:last-child {
        text-align: right;
    }
    .stRadio [role=radiogroup] label[data-baseweb="radio"] input:checked + div {
        background-color: #4CAF50;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# 메인 페이지 내용
# st.title("Coinone 매도 Tool", anchor=False)

# 주문 창
col_left, col_right = st.columns([1, 1])

with col_right:
    order_type_display = st.selectbox("주문 유형", ["지정가"], key='order_type')
    order_type = "LIMIT" if order_type_display == "지정가" else "MARKET" if order_type_display == "시장가" else "STOP_LIMIT"

    # 커스텀 라디오 버튼 스타일
    st.markdown("""
    <style>
    .stRadio [role=radiogroup] {
        flex-direction: row;
        justify-content: space-between;
    }
    .stRadio [role=radiogroup] label {
        width: 50%;
        padding: 10px;
        text-align: center;
        transition: all 0.3s ease;
    }
    .stRadio [role=radiogroup] label:first-child {
        text-align: left;
    }
    .stRadio [role=radiogroup] label:last-child {
        text-align: right;
    }
    .stRadio [role=radiogroup] label[data-baseweb="radio"] input:checked + div {
        background-color: #4CAF50;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

    side_display = st.radio("주문 종류", ["매도", "매수"], horizontal=True, key='side_radio')
    side = "SELL" if side_display == "매도" else "BUY"

    # 선택된 주문 종류에 따라 스타일 적용
    st.markdown(f"""
    <style>
        div[data-testid="stRadio"] > div > label:nth-child(1) {{
            text-align: {'left' if side == 'SELL' else 'center'};
        }}
        div[data-testid="stRadio"] > div > label:nth-child(2) {{
            text-align: {'center' if side == 'SELL' else 'right'};
        }}
    </style>
    """, unsafe_allow_html=True)

    if order_type != "MARKET":
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown("<div style='font-size: 1.1em; margin-bottom: 0.5em;'>매도 호가</div>", unsafe_allow_html=True)
            bids_df, asks_df = st.session_state.orderbook
            if asks_df is not None:
                # 첫 번째와 두 번째 행을 건너뛰고 나머지 행을 표시
                for i, ask in asks_df.iloc[2:].iterrows():
                    if st.button(f"{ask['price']:,.0f}", key=f"ask_btn_{i}", help="클릭하여 가격 선택"):
                        st.session_state.selected_price = f"{ask['price']:,.0f}"
            
            st.markdown("<div style='font-size: 1.1em; margin-top: 1em; margin-bottom: 0.5em;'>매수 호가</div>", unsafe_allow_html=True)
            if bids_df is not None and len(bids_df) > 0:
                highest_bid = bids_df['price'].max()
                for i in range(3):  # 3개의 매수 호가 표시
                    price = highest_bid + i
                    if st.button(f"{price:,.0f}", key=f"bid_btn_{i}", help="클릭하여 가격 선택"):
                        st.session_state.selected_price = f"{price:,.0f}"
            
            # 호가 정보 업데이트 버튼 추가
            if st.button("호가 정보 업데이트", key="update_orderbook"):
                st.session_state.orderbook = fetch_order_book()
                st.success("호가 정보가 업데이트되었습니다.")

        with col2:
            price_display = st.text_input("가격 (KRW)", st.session_state.get('selected_price', ''), key='price')
            st.markdown('<style>div[data-testid="stTextInput"] > div > div > input { font-size: 1rem !important; }</style>', unsafe_allow_html=True)
            price = price_display.replace(',', '') if price_display else None
    else:
        price = None

    percentage = st.slider("주문 비율 (%)", min_value=0, max_value=100, value=0, step=1, key='percentage')

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
                    available_krw = float(st.session_state.balances.get('krw', {}).get('available', '0'))
                    if side == "BUY":
                        amount_krw = available_krw * (percentage / 100)
                        quantity_value = amount_krw / price_value
                        quantity = f"{math.floor(quantity_value * 10000) / 10000:.4f}"  # 소수점 4자리까지 표시
                        krw_equivalent = amount_krw
                    else:
                        amount_usdt = available_usdt * (percentage / 100)
                        quantity_value = math.floor(amount_usdt * 10000) / 10000  # 소수점 4자리까지 내림
                        quantity = f"{quantity_value:.4f}"
                        krw_equivalent = quantity_value * price_value
        except ValueError:
            st.warning("유효한 가격을 입력해주세요.")
        
        st.markdown("<div class='small-font'>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            quantity_input = st.text_input("수량 (USDT)", value=quantity, disabled=True)
        with col2:
            st.write(f"환산 금액: {krw_equivalent:,.0f} KRW")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        quantity = st.text_input("수량 (USDT)", value="0")

    button_color = "sell-button" if side == "SELL" else "buy-button"
    
    if side == "BUY":
        button_text = f'<span style="float: right;">{side_display} 주문하기</span>'
    else:
        button_text = f'<span style="float: left;">{side_display} 주문하기</span>'

    if st.button(button_text, key="place_order", help="클릭하여 주문 실행", use_container_width=True):
        place_order(order_type, side, price, quantity)

    # 전체 시장가 매도 버튼 추가
    if st.button("전체 시장가 매도", key="market_sell_all", help="전체 USDT를 시장가로 매도", use_container_width=True):
        confirm = st.button("정말로 전체 USDT를 시장가로 매도하시겠습니까?", key="confirm_market_sell_all")
        if confirm:
            place_market_sell_all()

    st.markdown("</div>", unsafe_allow_html=True)

    # 미체결 주문 관련 기능 추가
    st.markdown("### 미체결 주문")
    orders = fetch_active_orders()

    if orders:
        for order in orders:
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            col1.write(f"종목: {order['target_currency']}")
            col2.write(f"유형: {order['type']}")
            col3.write(f"매수/매도: {order['side']}")
            col4.write(f"가격: {float(order['price']):,.2f}")
            col5.write(f"수량: {float(order['remain_qty']):,.4f}")
            if col6.button(f"취소", key=f"cancel_{order['order_id']}", help="클릭하여 주문 취소"):
                cancel_order(order['order_id'])
                st.rerun()
    else:
        st.info("미체결 주문 없음")

    # UUID 조회 기능 추가
    st.markdown("### 주문 조회")
    order_id_input = st.text_input("주문 ID 입력", key="order_id_input")
    if st.button("주문 조회", key="fetch_order_detail"):
        if order_id_input:
            order_detail = fetch_order_detail(order_id_input)
            if order_detail:
                st.write("주문 정보:")
                st.markdown(f"""
                <div style="font-size: 70%;">
                주문 ID: {order_detail['order_id']}<br><br>
                주문 유형: {order_detail['type']}<br><br>
                거래 화폐: {order_detail['quote_currency']}/{order_detail['target_currency']}<br><br>
                상태: {order_detail['status']}<br><br>
                매수/매도: {order_detail['side']}<br><br>
                주문 가격: {order_detail['price']} {order_detail['quote_currency']}<br><br>
                주문 수량: {order_detail['original_qty']} {order_detail['target_currency']}<br><br>
                체결된 수량: {order_detail['executed_qty']} {order_detail['target_currency']}<br><br>
                남은 수량: {order_detail['remain_qty']} {order_detail['target_currency']}<br><br>
                주문 시간: {datetime.fromtimestamp(int(order_detail['ordered_at'])/1000).strftime('%Y-%m-%d %H:%M:%S')}<br><br>
                마지막 업데이트: {datetime.fromtimestamp(int(order_detail['updated_at'])/1000).strftime('%Y-%m-%d %H:%M:%S')}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("해당 주문 ID로 주문을 찾을 수 없습니다.")
        else:
            st.warning("주문 ID를 입력해주세요.")


    # 최근 주문 정보 표시
    st.markdown("### 최근 주문 내역")
    logs = load_order_log()

    # 주문 시간을 기준으로 내림차순 정렬
    sorted_logs = sorted(logs, key=lambda x: x['timestamp'], reverse=True)

    # 최대 20개까지 표시
    for log in sorted_logs[:20]:
        # 타임스탬프를 datetime 객체로 변환
        timestamp = datetime.fromisoformat(log['timestamp'])
        # UTC 시간을 태국 시간으로 변환 (UTC+7)
        thailand_time = timestamp + timedelta(hours=7)
        # 초 단위까지만 포맷팅
        formatted_time = thailand_time.strftime("%Y-%m-%d %H:%M:%S")
        st.write(f"주문 시간(태국): {formatted_time}")
        order_id = log.get('order_id')
        if order_id is None or order_id == "null":
            # response 내부의 market_order에서 order_id 찾기
            response = log.get('response', {})
            market_order = response.get('market_order', {})
            order_id = market_order.get('order_id', '주문 ID 없음')
        
        st.write(f"{order_id}")
        st.write(f"가격: {log['price']} / 수량: {log['quantity']} / 상태: {log['status']}")
        st.write("---")  # 각 주문 사이에 구분선 추가
    

def place_market_sell_all(initial_balance=None, attempt=1):
    if attempt > 3:  # 최대 3번까지 시도
        st.error("최대 시도 횟수를 초과했습니다. 일부 USDT가 판매되지 않았을 수 있습니다.")
        return False

    balances = fetch_balances()
    usdt_balance = float(balances.get('usdt', {}).get('available', 0))
    
    if initial_balance is None:
        initial_balance = usdt_balance

    if usdt_balance > 0:
        # 소수점 첫째 자리 아래를 버림 처리
        sell_amount = math.floor(usdt_balance * 10) / 10
        result = place_order("MARKET", "SELL", None, str(sell_amount))
        
        if result:
            order_details = fetch_order_detail(result.get('order_id'))
            if order_details:
                executed_amount = float(order_details.get('executed_qty', 0))
                executed_price = float(order_details.get('avg_price', 0))
                
                remaining_balance = usdt_balance - executed_amount
                execution_ratio = executed_amount / initial_balance

                if execution_ratio >= 0.995:  # 99.5% 이상 실행됨
                    st.success(f"전체 USDT 중 {executed_amount:.1f} USDT가 평균 시장가 {executed_price:.2f} KRW에 매도되었습니다.")
                    return True
                else:
                    st.warning(f"{executed_amount:.1f} USDT가 매도되었습니다. 남은 수량을 다시 매도합니다.")
                    return place_market_sell_all(initial_balance, attempt + 1)
            else:
                st.warning(f"주문이 접수되었지만 상세 정보를 가져올 수 없습니다. 남은 수량을 다시 확인합니다.")
                return place_market_sell_all(initial_balance, attempt + 1)
        else:
            st.error("시장가 매도 중 오류가 발생했습니다.")
            return False
    else:
        if attempt == 1:
            st.error("판매할 USDT가 없습니다.")
        else:
            st.success("모든 USDT가 성공적으로 매도되었습니다.")
        return True
