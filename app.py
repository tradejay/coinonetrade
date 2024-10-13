import streamlit as st
import uuid  # 文件顶部添加此行

# Streamlit UI 设置
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
import os
from git import Repo

# Git 存储库设置
REPO_PATH = '.'  # 使用当前目录作为仓库
LOG_FILE = 'order_logs.json'

def init_git_repo():
    if not os.path.exists(os.path.join(REPO_PATH, '.git')):
        repo = Repo.init(REPO_PATH)
        # 创建初始提交
        open(os.path.join(REPO_PATH, LOG_FILE), 'a').close()  # 创建空日志文件
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
    logs = logs[-100:]  # 仅保留最近100条日志

    with open(os.path.join(REPO_PATH, LOG_FILE), 'w') as f:
        json.dump(logs, f, indent=2)

    repo.index.add([LOG_FILE])
    repo.index.commit(f"Update log: {datetime.now().isoformat()}")

# 用户信息（令牌及密钥） - 从 secrets.toml 获取
ACCESS_TOKEN = st.secrets.get("access_key", "")
SECRET_KEY = bytes(st.secrets.get("private_key", ""), 'utf-8')

# 本地环境下加载 secrets.toml 文件
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
        st.error("订单查询错误发生")
        return None

def get_encoded_payload(payload):
    payload['nonce'] = str(uuid.uuid4())  # 添加 nonce
    dumped_json = json.dumps(payload)
    encoded_json = base64.b64encode(dumped_json.encode('utf-8'))  # 添加 UTF-8 编码
    return encoded_json.decode('utf-8')  # 将结果解码为字符串

def get_signature(encoded_payload):
    signature = hmac.new(SECRET_KEY, encoded_payload.encode('utf-8'), hashlib.sha512)  # 编码 encoded_payload
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

    print(f"HTTP 状态码: {response.status}")
    try:
        json_content = json.loads(content.decode('utf-8'))
        if 'balances' in json_content:
            filtered_balances = [balance for balance in json_content['balances'] if balance['currency'] in ['KRW', 'USDT']]
            json_content['balances'] = filtered_balances

        print(f"过滤后的响应内容: {json.dumps(json_content, indent=2)}")
        return json_content
    except json.JSONDecodeError:
        print(f"响应内容（原始）: {content.decode('utf-8')}")
        return None

    try:
        json_content = json.loads(content.decode('utf-8'))
        if response.status == 200 and json_content.get('result') == 'success':
            return json_content
        else:
            error_code = json_content.get('error_code', '未知错误代码')
            error_msg = json_content.get('error_msg', '未知错误信息')
            st.error(f"API 请求错误: 代码 {error_code}, 信息: {error_msg}")
            return None
    except json.JSONDecodeError as e:
        st.error(f"JSONDecodeError: {e}")
        st.error(f"响应内容: {content.decode('utf-8')}")
        return None

def save_log(log_data):
    try:
        save_order_log(log_data)
        st.success("日志已成功保存。")
        
        # 显示日志
        st.markdown("### 最近订单日志")
        st.write(f"时间: {log_data['timestamp']}")
        st.write(f"订单类型: {log_data['order_type']}")
        st.write(f"买入/卖出: {log_data['side']}")
        st.write(f"价格: {log_data['price']}")
        st.write(f"数量: {log_data['quantity']}")
        st.write(f"状态: {log_data['status']}")
        st.write("---")
        
    except Exception as e:
        st.error(f"保存日志时发生错误: {str(e)}")

# 获取订单簿函数
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

            asks_df = asks_df.iloc[::-1]  # 卖出订单逆序排列
            return bids_df.head(5), asks_df.head(5)  # 仅显示前5个
        else:
            st.error(f"API 返回错误: {data.get('error_code', '未知错误')}")
    else:
        st.error(f"从 API 获取数据失败。状态码: {response.status_code}")
    return None, None

# 查询所有余额函数
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
        st.error("查询余额时发生错误")
        return {}

# 下单函数（支持买入和卖出）
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
            "price": f"{float(price):.2f}" if price else "",
            "qty": f"{float(quantity):.4f}",
            "post_only": False  # 添加此行
        }

        # 最小订单标准
        MIN_ORDER_AMOUNT_KRW = 1000
        MIN_ORDER_QTY_USDT = 0.001

        price_value = float(price) if price else 0
        quantity_value = float(quantity)

        if (order_type != "MARKET") and (price_value <= 0 or quantity_value <= 0):
            raise ValueError("价格和数量必须大于0。")
        
        if order_type != "MARKET":
            if price_value * quantity_value < MIN_ORDER_AMOUNT_KRW:
                raise ValueError(f"订单金额低于最小金额 {MIN_ORDER_AMOUNT_KRW} KRW。")

            if side == "BUY" and quantity_value < MIN_ORDER_QTY_USDT:
                raise ValueError(f"订单数量低于最小数量 {MIN_ORDER_QTY_USDT} USDT。")

        result = get_response(action, payload)

        if result and result.get('result') == 'success':
            order_id = result.get('order_id')
            st.success(f"{'买入' if side == 'BUY' else '卖出'}订单成功提交。订单 ID: {order_id}")
            log_data["status"] = "success"
            log_data["order_id"] = order_id
            log_data["response"] = result
            
            # 保存日志并提交到 Git
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
            st.error("下单时发生错误")
            log_data["status"] = "api_error"
            log_data["error_message"] = "API 响应失败"
            # 保存错误日志并提交到 Git
            save_order_log(log_data)

    except ValueError as e:
        st.error(f"输入错误: {e}")
        log_data["status"] = "input_error"
        log_data["error_message"] = str(e)
        # 保存错误日志并提交到 Git
        save_order_log(log_data)
    except Exception as e:
        st.error(f"下单处理时发生错误: {e}")
        log_data["status"] = "processing_error"
        log_data["error_message"] = str(e)
        # 保存错误日志并提交到 Git
        save_order_log(log_data)

    return log_data["status"] == "success"

# 查询未完成订单函数
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
        st.error("查询未完成订单时发生错误")
        return []

# 取消订单函数
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
        st.success(f"订单已成功取消。订单 ID: {order_id}")
    else:
        st.error("取消订单时发生错误")

# 自动更新余额和订单函数
def update_data():
    if st.session_state.get('last_update_time', 0) < time.time() - 0.5:
        st.session_state.balances = fetch_balances()
        st.session_state.orders = fetch_active_orders()
        st.session_state.orderbook = fetch_order_book()
        st.session_state.last_update_time = time.time()

# 显示余额信息函数
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
    ### 账户余额
    | 货币 | 总额 | 可用 | 限额 |
    |:-----|-----:|-----:|-----:|
    | KRW  | {:,.0f} | {:,.0f} | {:,.0f} |
    | USDT | {:,.2f} | {:,.2f} | {:,.2f} |
    """.format(total_krw, available_krw, limit_krw, total_usdt, available_usdt, limit_usdt))

# 初始会话状态设置
if 'orderbook' not in st.session_state:
    st.session_state.orderbook = fetch_order_book()

if 'balances' not in st.session_state:
    st.session_state.balances = fetch_balances()

if 'orders' not in st.session_state:
    st.session_state.orders = fetch_active_orders()

if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = 0

# 更新调用
update_data()

# 显示余额信息
update_balance_info()

# 样式设置
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
        background-color: #4CAF50 !important;  /* 稍浅绿色背景 */
        color: white !important;  /* 白色文字 */
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        opacity: 0.9;  /* 悬停时稍微透明 */
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
        background-color: #4b4bff !important;  /* 蓝色背景 */
        color: white !important;  /* 白色文字 */
    }
    .sell-button {
        background-color: #ff4b4b !important;  /* 红色背景 */
        color: white !important;  /* 白色文字 */
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

# 主页面内容
st.title("Coinone 交易工具", anchor=False)

# 创建左右两栏布局
col_left, col_right = st.columns([1, 1])

# 买入界面
with col_left:
    st.markdown("## 买入 (Buy)")
    buy_order_type_display = st.selectbox("订单类型", ["指定价"], key='buy_order_type')
    buy_order_type = "LIMIT" if buy_order_type_display == "指定价" else "MARKET" if buy_order_type_display == "市场价" else "STOP_LIMIT"

    buy_side_display = "买入"
    buy_side = "BUY"

    if buy_order_type != "MARKET":
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown("<div style='font-size: 1.1em; margin-bottom: 0.5em;'>买入价位</div>", unsafe_allow_html=True)
            bids_df, asks_df = st.session_state.orderbook
            if bids_df is not None:
                # 显示前两行
                for i, bid in bids_df.head(5).iterrows():
                    if st.button(f"{bid['price']:,.0f}", key=f"buy_bid_btn_{i}", help="点击选择价格"):
                        st.session_state.selected_buy_price = f"{bid['price']:,.0f}"
            
            st.markdown("<div style='font-size: 1.1em; margin-top: 1em; margin-bottom: 0.5em;'>卖出价位</div>", unsafe_allow_html=True)
            if bids_df is not None and len(bids_df) > 0:
                highest_bid = bids_df['price'].max()
                for i in range(2):
                    price = highest_bid + (i + 1)
                    if st.button(f"{price:,.0f}", key=f"buy_ask_btn_{i}", help="点击选择价格"):
                        st.session_state.selected_buy_price = f"{price:,.0f}"
            
            # 更新订单簿信息按钮
            if st.button("更新价位信息", key="update_buy_orderbook"):
                st.session_state.orderbook = fetch_order_book()
                st.success("价位信息已更新。")

        with col2:
            buy_price_display = st.text_input("价格 (KRW)", st.session_state.get('selected_buy_price', ''), key='buy_price')
            st.markdown('<style>div[data-testid="stTextInput"] > div > div > input { font-size: 1rem !important; }</style>', unsafe_allow_html=True)
            buy_price = buy_price_display.replace(',', '') if buy_price_display else None
    else:
        buy_price = None

    buy_percentage = st.slider("买入比例 (%)", min_value=0, max_value=100, value=0, step=1, key='buy_percentage')

    # 根据比例和价格计算数量
    buy_quantity = '0'
    krw_equivalent_buy = 0  # 以 KRW 计算的金额
    if buy_percentage > 0:
        try:
            if buy_order_type != "MARKET" and (buy_price is None or buy_price == ''):
                st.warning("请输入价格。")
            else:
                buy_price_value = float(buy_price) if buy_price else 0
                if buy_price_value <= 0:
                    st.warning("价格必须大于0。")
                else:
                    available_krw = float(st.session_state.balances.get('krw', {}).get('available', '0'))
                    amount_krw = available_krw * (buy_percentage / 100)
                    buy_quantity_value = amount_krw / buy_price_value
                    buy_quantity = f"{buy_quantity_value:.4f}"  # 保留四位小数
                    krw_equivalent_buy = amount_krw
        except ValueError:
            st.warning("请输入有效的价格。")
        
        st.markdown("<div class='small-font'>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            buy_quantity_input = st.text_input("数量 (USDT)", value=buy_quantity, disabled=True)
        with col2:
            st.write(f"等值金额: {krw_equivalent_buy:,.0f} KRW")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        buy_quantity = st.text_input("数量 (USDT)", value="0", key='buy_quantity_input')

    if st.button(f"{buy_side_display} 下单", key="place_buy_order", help="点击执行买入订单", css_class="buy-button"):
        place_order(buy_order_type, buy_side, buy_price, buy_quantity)

# 卖出界面
with col_right:
    st.markdown("## 卖出 (Sell)")
    order_type_display = st.selectbox("订单类型", ["指定价"], key='sell_order_type')
    order_type = "LIMIT" if order_type_display == "指定价" else "MARKET" if order_type_display == "市场价" else "STOP_LIMIT"

    side_display = "卖出"
    side = "SELL"

    if order_type != "MARKET":
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown("<div style='font-size: 1.1em; margin-bottom: 0.5em;'>卖出价位</div>", unsafe_allow_html=True)
            bids_df, asks_df = st.session_state.orderbook
            if asks_df is not None:
                # 跳过前两行，显示剩余行
                for i, ask in asks_df.iloc[2:].iterrows():
                    if st.button(f"{ask['price']:,.0f}", key=f"sell_ask_btn_{i}", help="点击选择价格"):
                        st.session_state.selected_sell_price = f"{ask['price']:,.0f}"
            
            st.markdown("<div style='font-size: 1.1em; margin-top: 1em; margin-bottom: 0.5em;'>买入价位</div>", unsafe_allow_html=True)
            if asks_df is not None and len(asks_df) > 0:
                lowest_ask = asks_df['price'].min()
                for i in range(2):
                    price = lowest_ask - (i + 1)
                    if st.button(f"{price:,.0f}", key=f"sell_bid_btn_{i}", help="点击选择价格"):
                        st.session_state.selected_sell_price = f"{price:,.0f}"
            
            # 更新订单簿信息按钮
            if st.button("更新价位信息", key="update_sell_orderbook"):
                st.session_state.orderbook = fetch_order_book()
                st.success("价位信息已更新。")

        with col2:
            price_display = st.text_input("价格 (KRW)", st.session_state.get('selected_sell_price', ''), key='sell_price')
            st.markdown('<style>div[data-testid="stTextInput"] > div > div > input { font-size: 1rem !important; }</style>', unsafe_allow_html=True)
            price = price_display.replace(',', '') if price_display else None
    else:
        price = None

    percentage = st.slider("卖出比例 (%)", min_value=0, max_value=100, value=0, step=1, key='sell_percentage')

    # 根据比例和价格计算数量
    quantity = '0'
    krw_equivalent = 0  # 以 KRW 计算的金额
    if percentage > 0:
        try:
            if order_type != "MARKET" and (price is None or price == ''):
                st.warning("请输入价格。")
            else:
                price_value = float(price)
                if price_value <= 0:
                    st.warning("价格必须大于0。")
                else:
                    available_usdt = float(st.session_state.balances.get('usdt', {}).get('available', '0'))
                    amount_usdt = available_usdt * (percentage / 100)
                    quantity_value = amount_usdt
                    quantity = f"{quantity_value:.4f}"  # 保留四位小数
                    krw_equivalent = quantity_value * price_value
        except ValueError:
            st.warning("请输入有效的价格。")
        
        st.markdown("<div class='small-font'>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            quantity_input = st.text_input("数量 (USDT)", value=quantity, disabled=True)
        with col2:
            st.write(f"等值金额: {krw_equivalent:,.0f} KRW")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        quantity = st.text_input("数量 (USDT)", value="0", key='sell_quantity_input')

    if st.button(f"{side_display} 下单", key="place_sell_order", help="点击执行卖出订单", css_class="sell-button"):
        place_order(order_type, side, price, quantity)

# 查看和取消未完成订单
st.markdown("### 未完成订单")
orders = st.session_state.orders
if orders:
    for order in orders:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.write(f"货币: {order['target_currency']}")
        col2.write(f"类型: {order['type']}")
        col3.write(f"价格: {float(order['price']):,.2f}")
        col4.write(f"数量: {float(order['remain_qty']):,.4f}")
        if col5.button(f"取消", key=f"cancel_{order['order_id']}", help="点击取消订单"):
            cancel_order(order['order_id'])
            st.rerun()
else:
    st.info("暂无未完成订单。")

# UUID 查询功能
st.markdown("### 查询订单")
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
            订单时间: {datetime.fromtimestamp(int(order_detail['ordered_at'])/1000).strftime('%Y-%m-%d %H:%M:%S')}<br><br>
            最后更新时间: {datetime.fromtimestamp(int(order_detail['updated_at'])/1000).strftime('%Y-%m-%d %H:%M:%S')}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("未找到对应订单 ID 的订单。")
    else:
        st.warning("请输入订单 ID。")

# 显示最近订单日志
st.markdown("### 最近订单记录")
logs = load_order_log()

# 按订单时间降序排序
sorted_logs = sorted(logs, key=lambda x: x['timestamp'], reverse=True)

# 最多显示20条
for log in sorted_logs[:20]:
    # 将时间戳转换为 datetime 对象
    timestamp = datetime.fromisoformat(log['timestamp'])
    # 将 UTC 时间转换为泰国时间（UTC+7）
    thailand_time = timestamp + timedelta(hours=7)
    # 仅格式化到秒
    formatted_time = thailand_time.strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"订单时间（泰国）: {formatted_time}")
    order_id = log.get('order_id')
    if order_id is None or order_id == "null":
        # 从响应内部的 market_order 查找 order_id
        response = log.get('response', {})
        market_order = response.get('market_order', {})
        order_id = market_order.get('order_id', '无订单 ID')
    
    st.write(f"订单 ID: {order_id}")
    st.write(f"价格: {log['price']} / 数量: {log['quantity']} / 状态: {log['status']}")
    st.write("---")  # 每个订单之间添加分隔线
