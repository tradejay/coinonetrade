import streamlit as st
import uuid

# Streamlit UI 设置
st.set_page_config(layout="wide")

from datetime import datetime, timedelta
import requests
import pandas as pd
import json
import base64
import hashlib
import hmac
import httplib2
import time
import math
import os
from git import Repo

# Git 仓库设置
REPO_PATH = '.'
LOG_FILE = 'order_logs.json'

def init_git_repo():
    if not os.path.exists(os.path.join(REPO_PATH, '.git')):
        repo = Repo.init(REPO_PATH)
        open(os.path.join(REPO_PATH, LOG_FILE), 'a').close()
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
    logs = logs[-100:]
    
    with open(os.path.join(REPO_PATH, LOG_FILE), 'w') as f:
        json.dump(logs, f, indent=2)
    
    repo.index.add([LOG_FILE])
    repo.index.commit(f"Update log: {datetime.now().isoformat()}")

# 用户信息（从 secrets.toml 获取）
ACCESS_TOKEN = st.secrets.get("access_key", "")
SECRET_KEY = bytes(st.secrets.get("private_key", ""), 'utf-8')

# 本地环境中加载 secrets.toml 文件
if not st.runtime.exists():
    from dotenv import load_dotenv
    load_dotenv('.streamlit/secrets.toml')

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
        st.error("订单查询出错")
        return None

def get_encoded_payload(payload):
    payload['nonce'] = str(uuid.uuid4())
    dumped_json = json.dumps(payload)
    encoded_json = base64.b64encode(dumped_json.encode('utf-8'))
    return encoded_json.decode('utf-8')

def get_signature(encoded_payload):
    signature = hmac.new(SECRET_KEY, encoded_payload.encode('utf-8'), hashlib.sha512)
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

    try:
        json_content = json.loads(content.decode('utf-8'))
        if 'balances' in json_content:
            filtered_balances = [balance for balance in json_content['balances'] if balance['currency'] in ['KRW', 'USDT']]
            json_content['balances'] = filtered_balances
        return json_content
    except json.JSONDecodeError:
        return None

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

            asks_df = asks_df.iloc[::-1]
            return bids_df.head(5), asks_df.head(5)
        else:
            st.error(f"API 错误: {data.get('error_code', 'Unknown error')}")
    else:
        st.error(f"无法从 API 获取数据，状态码: {response.status_code}")
    return None, None

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
        st.error("余额查询出错")
        return {}

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
            "post_only": False
        }

        MIN_ORDER_AMOUNT_KRW = 1000
        MIN_ORDER_QTY_USDT = 0.001

        price_value = float(price)
        quantity_value = float(quantity)

        if price_value <= 0 or quantity_value <= 0:
            raise ValueError("价格和数量必须大于0。")
        
        if price_value * quantity_value < MIN_ORDER_AMOUNT_KRW:
            raise ValueError(f"订单金额小于最小金额 {MIN_ORDER_AMOUNT_KRW} KRW。")

        if quantity_value < MIN_ORDER_QTY_USDT:
            raise ValueError(f"订单数量小于最小数量 {MIN_ORDER_QTY_USDT} USDT。")

        result = get_response(action, payload)

        if result and result.get('result') == 'success':
            order_id = result.get('order_id')
            st.success(f"{side} 订单已成功提交，订单 ID: {order_id}")
            log_data["status"] = "success"
            log_data["order_id"] = order_id
            log_data["response"] = result
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
            st.error("下单出错")
            log_data["status"] = "api_error"
            log_data["error_message"] = "API 响应失败"
            save_order_log(log_data)

    except ValueError as e:
        st.error(f"输入错误: {e}")
        log_data["status"] = "input_error"
        log_data["error_message"] = str(e)
        save_order_log(log_data)
    except Exception as e:
        st.error(f"处理订单时出错: {e}")
        log_data["status"] = "processing_error"
        log_data["error_message"] = str(e)
        save_order_log(log_data)

    return log_data["status"] == "success"

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
        st.error("查询未成交订单出错")
        return []

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
        st.success(f"订单已成功取消，订单 ID: {order_id}")
    else:
        st.error("取消订单出错")

def update_data():
    if st.session_state.get('last_update_time', 0) < time.time() - 0.5:
        st.session_state.balances = fetch_balances()
        st.session_state.orders = fetch_active_orders()
        st.session_state.orderbook = fetch_order_book()
        st.session_state.last_update_time = time.time()

def update_balance_info():
    balances = st.session_state.balances
    krw_balance = balances.get('krw', {})
    usdt_balance = balances.get('usdt', {})
    
    available_krw = float(krw_balance.get('available', '0'))
    total_krw = float(krw_balance.get('total', '0'))
    
    available_usdt = float(usdt_balance.get('available', '0'))
    total_usdt = float(usdt_balance.get('total', '0'))

    st.markdown("""
    ### 账户余额
    | 货币 | 总计 | 可用 |
    |:-----|-----:|-----:|
    | KRW  | {:,.0f} | {:,.0f} |
    | USDT | {:,.2f} | {:,.2f} |
    """.format(total_krw, available_krw, total_usdt, available_usdt))

if 'orderbook' not in st.session_state:
    st.session_state.orderbook = fetch_order_book()

update_data()
update_balance_info()

# 样式设置
st.markdown("""
<style>
    .reportview-container .main .block-container {
        padding: 1rem;
        max-width: 100%;
    }
    .stButton > button {
        width: 100%;
        padding: 0.1rem;
        font-size: 0.6rem;
        transition: all 0.3s ease;
        background-color: #4CAF50 !important;
        color: white !important;
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
</style>
""", unsafe_allow_html=True)

# 主页面内容
col_left, col_right = st.columns([1, 1])

with col_right:
    order_type_display = st.selectbox("订单类型", ["限价"], key='order_type')
    order_type = "LIMIT" if order_type_display == "限价" else "MARKET" if order_type_display == "市价" else "STOP_LIMIT"

    side_display = st.selectbox("买入/卖出", ["买入", "卖出"], key='side_display')
    side = "BUY" if side_display == "买入" else "SELL"

    if order_type != "MARKET":
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"<div style='font-size: 1.1em; margin-bottom: 0.5em;'>{'买入' if side=='BUY' else '卖出'} 报价</div>", unsafe_allow_html=True)
            bids_df, asks_df = st.session_state.orderbook
            if side == "BUY":
                if bids_df is not None:
                    for i, bid in bids_df.iterrows():
                        if st.button(f"{bid['price']:,.0f}", key=f"bid_btn_{i}", help="点击选择价格"):
                            st.session_state.selected_price = f"{bid['price']:,.0f}"
            else:
                if asks_df is not None:
                    for i, ask in asks_df.iterrows():
                        if st.button(f"{ask['price']:,.0f}", key=f"ask_btn_{i}", help="点击选择价格"):
                            st.session_state.selected_price = f"{ask['price']:,.0f}"
            if st.button("更新报价", key="update_orderbook"):
                st.session_state.orderbook = fetch_order_book()
                st.success("报价已更新。")

        with col2:
            price_display = st.text_input("价格 (KRW)", st.session_state.get('selected_price', ''), key='price')
            st.markdown('<style>div[data-testid="stTextInput"] > div > div > input { font-size: 1rem !important; }</style>', unsafe_allow_html=True)
            price = price_display.replace(',', '') if price_display else None
    else:
        price = None

    percentage = st.slider(f"{side_display} 比例 (%)", min_value=0, max_value=100, value=0, step=1, key='percentage')

    quantity = '0'
    krw_equivalent = 0
    if percentage > 0:
        try:
            if order_type != "MARKET" and (price is None or price == ''):
                st.warning("请输入价格。")
            else:
                price_value = float(price) if price else 0
                if price_value <= 0:
                    st.warning("价格必须大于0。")
                else:
                    available_usdt = float(st.session_state.balances.get('usdt', {}).get('available', '0'))
                    if side == "BUY":
                        available_krw = float(st.session_state.balances.get('krw', {}).get('available', '0'))
                        amount_krw = available_krw * (percentage / 100)
                        quantity_value = amount_krw / price_value
                        quantity = f"{quantity_value:.4f}"
                        krw_equivalent = amount_krw
                    else:
                        amount_usdt = available_usdt * (percentage / 100)
                        quantity_value = amount_usdt
                        quantity = f"{quantity_value:.4f}"
                        krw_equivalent = quantity_value * price_value
        except ValueError:
            st.warning("请输入有效的价格。")
        
        st.markdown("<div class='small-font'>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            quantity_input = st.text_input("数量 (USDT)", value=quantity, disabled=True)
        with col2:
            st.write(f"折合金额: {krw_equivalent:,.0f} KRW")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        quantity = st.text_input("数量 (USDT)", value="0")

    if st.button(f"{side_display} 下单", key="place_order", help="点击执行订单"):
        place_order(order_type, side, price, quantity)

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### 未成交订单")
    orders = fetch_active_orders()
    
    if orders:
        for order in orders:
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.write(f"品种: {order['target_currency']}")
            col2.write(f"类型: {order['type']} ({'买入' if order['side']=='BUY' else '卖出'})")
            col3.write(f"价格: {float(order['price']):,.2f}")
            col4.write(f"数量: {float(order['remain_qty']):,.4f}")
            if col5.button(f"取消", key=f"cancel_{order['order_id']}", help="点击取消订单"):
                cancel_order(order['order_id'])
                st.rerun()
    else:
        st.info("无未成交订单")

    st.markdown("### 订单查询")
    order_id_input = st.text_input("输入订单 ID", key="order_id_input")
    if st.button("查询订单", key="fetch_order_detail"):
        if order_id_input:
            order_detail = fetch_order_detail(order_id_input)
            if order_detail:
                st.write("订单信息:")
                st.markdown(f"""
                <div style="font-size: 70%;">
                订单 ID: {order_detail['order_id']}<br><br>
                订单类型: {order_detail['type']}<br><br>
                交易货币: {order_detail['quote_currency']}/{order_detail['target_currency']}<br><br>
                状态: {order_detail['status']}<br><br>
                买入/卖出: {order_detail['side']}<br><br>
                订单价格: {order_detail['price']} {order_detail['quote_currency']}<br><br>
                订单数量: {order_detail['original_qty']} {order_detail['target_currency']}<br><br>
                已成交数量: {order_detail['executed_qty']} {order_detail['target_currency']}<br><br>
                剩余数量: {order_detail['remain_qty']} {order_detail['target_currency']}<br><br>
                下单时间: {datetime.fromtimestamp(int(order_detail['ordered_at'])/1000).strftime('%Y-%m-%d %H:%M:%S')}<br><br>
                最后更新: {datetime.fromtimestamp(int(order_detail['updated_at'])/1000).strftime('%Y-%m-%d %H:%M:%S')}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("找不到该订单 ID 的订单。")
        else:
            st.warning("请输入订单 ID。")

    st.markdown("### 最近订单记录")
    logs = load_order_log()

    sorted_logs = sorted(logs, key=lambda x: x['timestamp'], reverse=True)

    for log in sorted_logs[:20]:
        timestamp = datetime.fromisoformat(log['timestamp'])
        formatted_time = (timestamp + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
        st.write(f"订单时间(泰国): {formatted_time}")
        order_id = log.get('order_id', '无订单 ID')
        st.write(f"{order_id}")
        st.write(f"价格: {log['price']} / 数量: {log['quantity']} / 状态: {log['status']}")
        st.write("---")
