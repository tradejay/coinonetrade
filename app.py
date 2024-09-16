import streamlit as st

# 페이지 제목 설정
st.title('Hello Streamlit!')

# 텍스트 출력
st.write('Welcome to your first Streamlit app!')

# 사용자 입력 받기
name = st.text_input('Enter your name:')
if name:
    st.write(f'Hello!!, {name}!')

# 슬라이더 사용
age = st.slider('Select your age:', 0, 100, 25)
st.write(f'You are {age} years old.')

# 차트 그리기
st.write('Here is a simple line chart:')
st.line_chart([1, 3, 2, 4, 5])
