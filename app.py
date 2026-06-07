"""
Data Chat — Conversational analytics on your Fabric Lakehouse / SQL Server.
Ask questions in natural language; AI generates SQL, executes it, and returns
insights + interactive charts.
"""

import streamlit as st
from streamlit_local_storage import LocalStorage

from config.settings import ENV_CONFIGS, AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, FABRIC_DATABASE
from core.auth import check_password, restore_auth, logout
from core.database import list_fabric_databases, check_odbc_driver, run_query
from services.schema import get_schema_context, invalidate_schema_cache
from services.azure_ai import DataChatAI, AIError
from services.query_evaluator import QueryEvaluatorAI, QueryEvaluationError
from ui.css import inject_css

# ─── Auth (y chang data-catalog) ──────────────────────────────────────────────
ls = LocalStorage()

if "_ls_synced" not in st.session_state:
    st.session_state["_ls_synced"] = True
    st.rerun()

restore_auth(ls)
check_password()

# ─── Page config ──────────────────────────────────────────────────────────────
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


def render_evaluation_response(resp: dict):
    if resp.get("error"):
        st.error(resp["error"])
        return

    verdict = resp.get("verdict", "warning")
    verdict_label = {
        "pass": "Đạt",
        "warning": "Cần kiểm tra",
        "fail": "Không đạt",
    }.get(verdict, "Cần kiểm tra")

    if verdict == "pass":
        st.success(f"**Kết luận:** {verdict_label}")
    elif verdict == "fail":
        st.error(f"**Kết luận:** {verdict_label}")
    else:
        st.warning(f"**Kết luận:** {verdict_label}")

    col1, col2 = st.columns(2)
    col1.metric("Đúng điều kiện", f"{resp.get('condition_score', 0)}/100")
    col2.metric("Đúng source", f"{resp.get('source_score', 0)}/100")

    if resp.get("notes"):
        st.markdown(resp["notes"])

    used_sources = resp.get("used_sources") or []
    expected_sources = resp.get("expected_sources") or []
    if used_sources or expected_sources:
        with st.expander("🗄️ Source", expanded=True):
            if expected_sources:
                st.markdown("**Source kỳ vọng:** " + ", ".join(f"`{src}`" for src in expected_sources))
            if used_sources:
                st.markdown("**Source query đang dùng:** " + ", ".join(f"`{src}`" for src in used_sources))

    issues = []
    for label, key in [
        ("Thiếu/sai điều kiện", "missing_conditions"),
        ("Vấn đề source", "source_issues"),
        ("Vấn đề an toàn", "safety_issues"),
    ]:
        values = resp.get(key) or []
        if values:
            issues.append((label, values))

    if issues:
        with st.expander("⚠️ Điểm cần sửa", expanded=True):
            for label, values in issues:
                st.markdown(f"**{label}**")
                for value in values:
                    st.markdown(f"- {value}")

    if resp.get("recommendation"):
        st.info(resp["recommendation"])

    if resp.get("corrected_sql"):
        with st.expander("✅ SQL đề xuất", expanded=False):
            st.code(resp["corrected_sql"], language="sql")


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 💬 Data Chat")
    st.caption("AI analytics trên dữ liệu lakehouse của bạn")
    if st.button("🚪 Đăng xuất", use_container_width=True):
        logout(ls)
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
        st.session_state.pop("fabric_database", None)
        st.rerun()

    # Fabric database selector
    if st.session_state.env == "fabric":
        if "fabric_db_list" not in st.session_state:
            with st.spinner("Đang tải danh sách database..."):
                db_list = list_fabric_databases()
                if not db_list and FABRIC_DATABASE:
                    db_list = [FABRIC_DATABASE]
                st.session_state.fabric_db_list = db_list

        db_list = st.session_state.get("fabric_db_list", [FABRIC_DATABASE])

        if "fabric_database" not in st.session_state:
            default_db = FABRIC_DATABASE if FABRIC_DATABASE in db_list else (db_list[0] if db_list else "")
            st.session_state.fabric_database = default_db

        prev_db = st.session_state.fabric_database
        chosen_db = st.selectbox(
            "Database / Warehouse",
            options=db_list,
            index=db_list.index(prev_db) if prev_db in db_list else 0,
            key="_db_selector",
        )
        if chosen_db != prev_db:
            st.session_state.fabric_database = chosen_db
            st.rerun()

    st.divider()

    # Azure OpenAI settings
    st.markdown("### 🤖 Azure OpenAI")
    if AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT:
        api_key = AZURE_OPENAI_KEY
        endpoint = AZURE_OPENAI_ENDPOINT
        deployment = AZURE_OPENAI_DEPLOYMENT
        st.caption(f"Endpoint: `{endpoint}`")
        st.caption(f"Deployment: `{deployment}`")
    else:
        api_key = st.text_input(
            "API Key",
            type="password",
            key="azure_api_key",
            placeholder="••••••••••••••••",
        )
        endpoint = st.text_input(
            "Endpoint",
            key="azure_endpoint",
            value=st.session_state.get("azure_endpoint", ""),
        )
        deployment = st.text_input(
            "Deployment Name",
            key="azure_deployment",
            value=st.session_state.get("azure_deployment", "gpt-5"),
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
            st.session_state.evaluator_messages = []
            st.rerun()

    # Schema stats
    if "_schema_info" in st.session_state:
        info = st.session_state["_schema_info"]
        st.caption(f"Schema: **{info['tables']}** bảng · **{info['cols']}** cột")


# ─── Main area ────────────────────────────────────────────────────────────────

check_odbc_driver()

# Load schema metadata once per environment/database, then reuse cache.
with st.spinner("Đang tải cấu trúc database..."):
    try:
        schema_text = get_schema_context()
        st.session_state["_schema_info"] = {
            "tables": schema_text.count("TABLE:"),
            "cols": schema_text.count("\n  - "),
        }
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

data_tab, evaluator_tab = st.tabs(["💬 Data Chat", "✅ Đánh giá query"])

with data_tab:
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    data_history = st.container()
    with data_history:
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

    # ─── Chat Input ───────────────────────────────────────────────────────────

    prompt = st.chat_input(
        "Hỏi về dữ liệu của bạn...",
        disabled=not ai_ready,
        key="data_chat_input",
    )

    if prompt:
        # Show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with data_history:
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
        with data_history:
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

with evaluator_tab:
    if "evaluator_messages" not in st.session_state:
        st.session_state.evaluator_messages = []

    evaluator_history = st.container()
    with evaluator_history:
        if not st.session_state.evaluator_messages:
            with st.chat_message("assistant"):
                st.markdown(
                    """
Paste requirement, expected source và SQL cần kiểm tra. Ví dụ:

```text
Yêu cầu: doanh thu theo tháng trong năm 2026, chỉ lấy đơn đã hoàn tất
Source kỳ vọng: dbo.FactSales, dbo.DimDate
SQL:
SELECT ...
```
"""
                )

        for msg in st.session_state.evaluator_messages:
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    render_evaluation_response(msg)
                else:
                    st.markdown(msg["content"])

    evaluator_prompt = st.chat_input(
        "Paste requirement + source kỳ vọng + SQL để đánh giá...",
        disabled=not ai_ready,
        key="query_evaluator_input",
    )

    if evaluator_prompt:
        st.session_state.evaluator_messages.append({"role": "user", "content": evaluator_prompt})
        with evaluator_history:
            with st.chat_message("user"):
                st.markdown(evaluator_prompt)

        history = []
        for m in st.session_state.evaluator_messages[:-1]:
            if m["role"] == "user":
                history.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                content = (
                    f"Verdict: {m.get('verdict')}. "
                    f"Condition score: {m.get('condition_score')}. "
                    f"Source score: {m.get('source_score')}. "
                    f"Notes: {m.get('notes', '')}"
                )
                history.append({"role": "assistant", "content": content})
        history = history[-8:]

        with evaluator_history:
            with st.chat_message("assistant"):
                status = st.status("Đang đánh giá query...", expanded=False)

                try:
                    evaluator = QueryEvaluatorAI(
                        api_key=api_key,
                        endpoint=endpoint,
                        deployment=deployment,
                    )
                    with status:
                        st.write("Đang kiểm tra điều kiện và source...")
                        eval_resp = evaluator.evaluate(
                            message=evaluator_prompt,
                            schema=schema_text,
                            history=history,
                        )
                    status.update(label="Hoàn thành ✓", state="complete", expanded=False)
                except QueryEvaluationError as exc:
                    status.update(label="Lỗi", state="error")
                    eval_resp = {"role": "assistant", "error": str(exc)}
                except Exception as exc:
                    status.update(label="Lỗi không mong đợi", state="error")
                    eval_resp = {"role": "assistant", "error": f"Lỗi: {exc}"}

                render_evaluation_response(eval_resp)

        eval_resp["role"] = "assistant"
        st.session_state.evaluator_messages.append(eval_resp)
