"""
Simple password protection with signed token persistence via browser LocalStorage.
Credentials from st.secrets["username"] and st.secrets["password"].
"""

import hashlib
import hmac
import streamlit as st

_LS_KEY = "datachat_auth"


def _sign(username: str) -> str:
    secret = st.secrets["password"].encode()
    return hmac.new(secret, username.encode(), hashlib.sha256).hexdigest()


def _make_token(username: str) -> str:
    return f"{username}|{_sign(username)}"


def _verify_token(token: str) -> bool:
    if not token or "|" not in token:
        return False
    username, sig = token.rsplit("|", 1)
    return hmac.compare_digest(sig, _sign(username))


def check_password():
    if "password" not in st.secrets:
        return True

    if st.session_state.get("authenticated"):
        return True

    st.set_page_config(page_title="Đăng nhập", page_icon="🔒")
    st.title("🔒 Data Chat")

    with st.form("login_form"):
        user = st.text_input("Tên đăng nhập")
        pw = st.text_input("Mật khẩu", type="password")
        submitted = st.form_submit_button("Đăng nhập", use_container_width=True)

    if submitted:
        if (
            hmac.compare_digest(user, st.secrets["username"])
            and hmac.compare_digest(pw, st.secrets["password"])
        ):
            st.session_state["authenticated"] = True
            st.session_state["_just_logged_in"] = True
            st.rerun()
        else:
            st.error("Tên đăng nhập hoặc mật khẩu không đúng.")

    st.stop()


def restore_auth(ls):
    """Gọi sau khi LocalStorage được khởi tạo để restore hoặc lưu auth token."""
    if st.session_state.get("authenticated"):
        if st.session_state.pop("_just_logged_in", False):
            ls.setItem(_LS_KEY, _make_token(st.secrets["username"]))
        return

    saved = ls.getItem(_LS_KEY)
    if saved and _verify_token(saved):
        st.session_state["authenticated"] = True


def logout(ls):
    ls.deleteItem(_LS_KEY)
    st.session_state.clear()
    st.rerun()
