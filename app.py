"""
Data Chat — Conversational analytics on your Fabric Lakehouse / SQL Server.
Ask questions in natural language; AI generates SQL, executes it, and returns
insights + interactive charts.
"""

import streamlit as st

from config.settings import ENV_CONFIGS
from core.database import check_odbc_driver, run_query
from services.schema import get_schema_context, invalidate_schema_cache
from services.azure_ai import DataChatAI, AIError
from ui.css import inject_css

# ─── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="Data Chat",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ─── Helper: render one assistant response dict ───────────────────────────────

def render_response(resp: dict):
    if resp.get("error"):
        st.error(resp["error"])

    if resp.get("insights"):
        st.markdown(resp["insights"])

    if resp.get("chart_fig") is not None:
        st.plotly_chart(resp["chart_fig"], use_container_width=True)

    df = resp.get("data")
    if df is not None and not df.empty:
        label = f"📊 Dữ liệu · {len(df):,} hàng, {len(df.columns)} cột"
        with st.expander(label, expanded=False):
            st.dataframe(df, use_container_width=True, hide_index=True)

    if resp.get("sql"):
        with st.expander("🔍 SQL đã thực thi", expanded=False):
            st.code(resp["sql"], language="sql")


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 💬 Data Chat")
    st.caption("AI analytics trên dữ liệu lakehouse của bạn")
    st.divider()

    # Environment selector
    st.markdown("### 🗄️ Nguồn dữ liệu")
    env_keys = list(ENV_CONFIGS.keys())
    env_labels = {k: v["label"] for k, v in ENV_CONFIGS.items()}

    if "env" not in st.session_state:
        st.session_state.env = env_keys[0]

    prev_env = st.session_state.env
    chosen_env = st.selectbox(
        "Môi trường",
        options=env_keys,
        format_func=lambda k: env_labels[k],
        index=env_keys.index(st.session_state.env),
        key="_env_selector",
    )
    if chosen_env != prev_env:
        st.session_state.env = chosen_env
        invalidate_schema_cache()
        st.rerun()

    st.divider()

    # Azure OpenAI settings
    st.markdown("### 🤖 Azure OpenAI")
    api_key = st.text_input(
        "API Key",
        type="password",
        key="azure_api_key",
        placeholder="••••••••••••••••",
        help="Lấy từ Azure Portal → Azure OpenAI resource → Keys and Endpoint",
    )
    endpoint = st.text_input(
        "Endpoint",
        key="azure_endpoint",
        placeholder="https://<resource>.openai.azure.com/",
    )
    deployment = st.text_input(
        "Deployment Name",
        key="azure_deployment",
        value=st.session_state.get("azure_deployment", "gpt-4o"),
        placeholder="gpt-4o",
        help="Tên deployment trong Azure OpenAI Studio",
    )

    ai_ready = bool(api_key and endpoint and deployment)
    if not ai_ready:
        st.info("Nhập API Key và Endpoint để bắt đầu.", icon="ℹ️")

    st.divider()

    # Schema / chat controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Schema", use_container_width=True, help="Tải lại cấu trúc database"):
            invalidate_schema_cache()
            st.rerun()
    with col2:
        if st.button("🗑️ Xóa chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    # Schema stats
    if "_schema_info" in st.session_state:
        info = st.session_state["_schema_info"]
        st.caption(f"Schema: **{info['tables']}** bảng · **{info['cols']}** cột")


# ─── Main area ────────────────────────────────────────────────────────────────

check_odbc_driver()

# Load schema (cached in session state per env)
if get_schema_context.__name__ and "_schema_loaded" not in st.session_state:
    with st.spinner("Đang tải cấu trúc database..."):
        try:
            schema_text = get_schema_context()
            # Cache stats for sidebar display
            st.session_state["_schema_info"] = {
                "tables": schema_text.count("TABLE:"),
                "cols": schema_text.count("\n  - "),
            }
            st.session_state["_schema_loaded"] = True
        except Exception as exc:
            st.error(f"Không thể tải schema: {exc}")
            st.stop()
else:
    try:
        schema_text = get_schema_context()
    except Exception as exc:
        st.error(f"Không thể tải schema: {exc}")
        st.stop()

# Header
env_label = env_labels[st.session_state.env]
info = st.session_state.get("_schema_info", {})
st.markdown(f"# 💬 Data Chat")
st.caption(
    f"Kết nối tới **{env_label}** · "
    f"{info.get('tables', '?')} bảng · "
    f"{info.get('cols', '?')} cột"
)

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Greeting for empty chat
if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown(
            """
👋 **Xin chào! Tôi có thể giúp bạn phân tích dữ liệu trong lakehouse.**

Hãy đặt câu hỏi bằng tiếng Việt hoặc tiếng Anh. Ví dụ:

- *"Top 10 khách hàng theo doanh thu tháng này?"*
- *"Xu hướng đơn hàng theo tháng trong 6 tháng gần đây?"*
- *"Sản phẩm nào có tỷ lệ trả hàng cao nhất?"*
- *"Có bao nhiêu đơn hàng bị delay trong quý này?"*
"""
        )

# Render existing chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            render_response(msg)
        else:
            st.markdown(msg["content"])

# ─── Chat Input ───────────────────────────────────────────────────────────────

prompt = st.chat_input(
    "Hỏi về dữ liệu của bạn...",
    disabled=not ai_ready,
)

if prompt:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build history for AI context (last 8 turns, use summaries for assistant)
    history = []
    for m in st.session_state.messages[:-1]:
        if m["role"] == "user":
            history.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            summary = m.get("summary") or m.get("insights") or ""
            if summary:
                history.append({"role": "assistant", "content": summary})
    history = history[-8:]

    # Generate response
    with st.chat_message("assistant"):
        status = st.status("Đang phân tích...", expanded=False)

        try:
            ai = DataChatAI(
                api_key=api_key,
                endpoint=endpoint,
                deployment=deployment,
            )

            with status:
                st.write("Đang tạo truy vấn SQL...")
                resp = ai.answer(
                    question=prompt,
                    schema=schema_text,
                    history=history,
                    run_query_fn=run_query,
                )

            status.update(label="Hoàn thành ✓", state="complete", expanded=False)

        except AIError as exc:
            status.update(label="Lỗi", state="error")
            resp = {
                "error": str(exc),
                "insights": None,
                "sql": None,
                "data": None,
                "chart_fig": None,
                "summary": f"Error: {exc}",
            }
        except Exception as exc:
            status.update(label="Lỗi không mong đợi", state="error")
            resp = {
                "error": f"Lỗi: {exc}",
                "insights": None,
                "sql": None,
                "data": None,
                "chart_fig": None,
                "summary": f"Unexpected error: {exc}",
            }

        render_response(resp)

    # Save to history (without the DataFrame to keep session state lean)
    resp_to_store = {k: v for k, v in resp.items() if k != "data"}
    resp_to_store["role"] = "assistant"
    # Re-attach data shape info for display on re-render
    df = resp.get("data")
    if df is not None:
        resp_to_store["data"] = df
    st.session_state.messages.append(resp_to_store)
