import streamlit as st
import base64
import hashlib
import hmac
import json
import uuid
import httplib2
import time

# 사용자 정보 (토큰 및 키) - secrets.toml에서 가져오기
ACCESS_TOKEN = st.secrets["access_key"]
SECRET_KEY = bytes(st.secrets["private_key"], 'utf-8')

# API 요청 함수 정의
def get_encoded_payload(payload):
    payload['nonce'] = str(uuid.uuid4())
    dumped_json = json.dumps(payload)
    encoded_json = base64.b64encode(bytes(dumped_json, 'utf-8'))
    return encoded_json

def get_signature(encoded_payload):
    signature = hmac.new(SECRET_KEY, encoded_payload, hashlib.sha512)
    return signature.hexdigest()

def get_response(action, payload):
    url = '{}{}'.format('https://api.coinone.co.kr', action)
    encoded_payload = get_encoded_payload(payload)
    headers = {
        'Content-type': 'application/json',
        'X-COINONE-PAYLOAD': encoded_payload,
        'X-COINONE-SIGNATURE': get_signature(encoded_payload),
    }
    http = httplib2.Http()
    response, content = http.request(url, 'POST', headers=headers)
    return json.loads(content)

def get_price(currency):
    url = f'https://api.coinone.co.kr/ticker?currency={currency}'
    http = httplib2.Http()
    response, content = http.request(url, 'GET')
    return json.loads(content)

# 자산 조회 및 가격 실시간 업데이트
def get_balance():
    response = get_response('/v2/account/balance/', {'access_token': ACCESS_TOKEN})
    return response.get('balance', {})

def place_order(order_type, currency, price, qty):
    action = '/v2.1/order'
    payload = {
        'access_token': ACCESS_TOKEN,
        'quote_currency': 'KRW',
        'target_currency': currency,
        'type': 'LIMIT',
        'side': order_type,
        'qty': str(qty),
        'price': str(price),
        'post_only': True
    }
    return get_response(action, payload)

# Streamlit 인터페이스
st.set_page_config(page_title="Coinone Trade", layout="wide")
st.title("Coinone Trading Interface")

# 실시간 자산 및 가격 업데이트
st.sidebar.header("보유 자산")
balances = get_balance()
krw_balance = float(balances.get('krw', {}).get('avail', 0))
btc_balance = float(balances.get('btc', {}).get('avail', 0))
eth_balance = float(balances.get('eth', {}).get('avail', 0))

st.sidebar.write(f"KRW: {krw_balance:,.0f} 원")
st.sidebar.write(f"BTC: {btc_balance:.8f} 개")
st.sidebar.write(f"ETH: {eth_balance:.8f} 개")

# 실시간 가격 업데이트
currency = st.sidebar.selectbox("조회할 코인 선택", ["BTC", "ETH"])
price_info = st.empty()

def update_price():
    while True:
        price = get_price(currency.lower())
        current_price = price.get('last', 'N/A')
        price_info.write(f"현재 {currency} 가격: {current_price} KRW")
        time.sleep(1)  # 1초마다 가격 업데이트

# 실시간 가격 업데이트 호출
update_price()

# 매수/매도 선택
tab1, tab2 = st.tabs(["매수", "매도"])

# 매수 인터페이스
with tab1:
    st.header("매수 주문")
    buy_currency = st.selectbox("매수할 코인 선택", ["BTC", "ETH"])
    buy_price = st.number_input("매수 가격 (KRW)", value=0, step=1)
    buy_qty = st.number_input("매수 수량", value=0.0, step=0.0001)
    buy_ratio = st.slider("KRW 자산 비율로 매수", 0, 100, 0)

    if buy_ratio > 0:
        buy_qty = (krw_balance * buy_ratio / 100) / buy_price

    if st.button("매수 주문 실행"):
        result = place_order('BUY', buy_currency.lower(), buy_price, buy_qty)
        st.write("매수 주문 결과:", result)

# 매도 인터페이스
with tab2:
    st.header("매도 주문")
    sell_currency = st.selectbox("매도할 코인 선택", ["BTC", "ETH"], index=0)
    sell_price = st.number_input("매도 가격 (KRW)", value=0, step=1)
    sell_qty = st.number_input("매도 수량", value=0.0, step=0.0001)
    sell_ratio = st.slider("보유 자산 비율로 매도", 0, 100, 0)

    if sell_currency == "BTC":
        max_qty = btc_balance
    else:
        max_qty = eth_balance

    if sell_ratio > 0:
        sell_qty = max_qty * sell_ratio / 100

    if st.button("매도 주문 실행"):
        result = place_order('SELL', sell_currency.lower(), sell_price, sell_qty)
        st.write("매도 주문 결과:", result)
