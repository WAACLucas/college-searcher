import streamlit as st
import json, os, re, tempfile
import pandas as pd
import pdfplumber

st.set_page_config(page_title="高考录取辅助查询", page_icon="🎓", layout="centered")
st.markdown("<style>#MainMenu{visibility:hidden}footer{visibility:hidden}</style>", unsafe_allow_html=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin888")
DATA_PATH = "data.json"

# ---- 数据加载 ----
def load_data():
    if "custom_data" in st.session_state and st.session_state.custom_data:
        return st.session_state.custom_data
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["data"]

def data_info():
    if "custom_data" in st.session_state and st.session_state.custom_data:
        return st.session_state.custom_info, st.session_state.custom_year
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)["meta"]
    except:
        return "投档数据未加载", ""
    year = meta.get("year", "")
    return f"📊 参考数据：{meta['source']}（共{meta['count']}条）", year

# ---- PDF解析 ----
def parse_pdf(filepath):
    vols = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or not row[0] or not row[0].strip(): continue
                    vn = str(row[0]).strip()
                    sf = str(row[1]).strip().replace("\n","") if len(row)>1 else ""
                    mf = str(row[3]).strip().replace("\n","") if len(row)>3 else ""
                    if vn == "志愿号" or not vn.isdigit(): continue
                    if not sf or sf == "None": continue
                    sc = sf[:4]
                    mt = re.match(r"^([A-Za-z0-9]+)", mf)
                    mc = mt.group(1) if mt else ""
                    mn = mf[len(mc):] if mc else mf
                    vols.append((int(vn), sf, sc, mc, mn))
    vols.sort(key=lambda x: x[0])
    seen = set(); uniq = []
    for v in vols:
        if v[0] not in seen: seen.add(v[0]); uniq.append(v)
    return uniq

# ---- 粘贴文本解析 ----


def parse_text(text):
    """解析粘贴的志愿文本。支持精简格式(1 A558 2Y)和完整格式(从官方PDF复制)"""
    lines = [l.strip() for l in text.strip().split(chr(10)) if l.strip()]
    if not lines: return []
    entries = []
    for i, line in enumerate(lines):
        # 精简格式：序号 院校代码 专业代码
        sm = re.match(r"^(\d{1,3})\s+([A-Z][A-Z0-9]{3})\s+([A-Za-z0-9]+)", line)
        if sm:
            entries.append((int(sm.group(1)), sm.group(2), sm.group(3)))
            continue
        # 完整格式：序号+院校代码
        fm = re.match(r"^(\d{1,3})\s*([A-Z][A-Z0-9]{3})", line)
        if not fm: continue
        vn, sc = int(fm.group(1)), fm.group(2)
        mc = ""
        # 从本行找专业代码
        rest_part = line[len(fm.group(0)):]
        ti = rest_part.find("公办院校")
        if ti < 0: ti = rest_part.find("民办院校")
        if ti >= 0:
            after = rest_part[ti+4:]
            after = re.sub(r"\s*(本科|专科)\s*\d*\s*$", "", after).strip()
            mm = re.match(r"^([A-Za-z0-9]+)", after)
            if mm: mc = mm.group(1)
        # 本行没有则看上一行
        if not mc and i > 0:
            pm = re.match(r"^([A-Za-z0-9]+)", lines[i-1])
            if pm:
                if not re.match(r"^\d{1,3}\s*[A-Z][A-Z0-9]{3}", lines[i-1]):
                    mc = pm.group(1)
        entries.append((vn, sc, mc))
    seen, result = set(), []
    for vn, sc, mc in entries:
        if vn not in seen: seen.add(vn); result.append((vn, sc, mc))
    return result


# ---- 核心分析 ----
def judge(rank, lookup, vols):
    results = []
    matched = False
    for item in vols:
        if len(item) == 5:
            vn, sf, sc, mc, mn = item
            key = sc + "|" + mc
            if matched:
                results.append({"志愿号": vn, "院校": sf, "专业": (mc + mn)[:20], "最低位次": "—", "结果": "已录取（后续不再判断）"})
                continue
            if key in lookup:
                mr = lookup[key]
                if rank <= mr:
                    results.append({"志愿号": vn, "院校": sf, "专业": mc + mn, "最低位次": mr, "结果": "✅ 录取"})
                    matched = True
                else:
                    results.append({"志愿号": vn, "院校": sf, "专业": (mc + mn)[:20], "最低位次": mr, "结果": "位次不够"})
            else:
                results.append({"志愿号": vn, "院校": sf, "专业": (mc + mn)[:20], "最低位次": "—", "结果": "无匹配"})
        elif len(item) == 3:
            vn, sc, mc = item
            key = sc + "|" + mc
            if matched:
                results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": "—", "结果": "已录取（后续不再判断）"})
                continue
            if key in lookup:
                mr = lookup[key]
                if rank <= mr:
                    results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": mr, "结果": "✅ 录取"})
                    matched = True
                else:
                    results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": mr, "结果": "位次不够"})
            else:
                results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": "—", "结果": "无匹配"})
    return results, matched

# ===== UI =====
if "input_mode" not in st.session_state:
    st.session_state.input_mode = None
if "pdf_vols" not in st.session_state:
    st.session_state.pdf_vols = None
if "text_vols" not in st.session_state:
    st.session_state.text_vols = None

st.title("\U0001f3ab \u9ad8\u8003\u5f55\u53d6\u8f85\u52a9\u67e5\u8be2")
st.caption("\U0001f4cd \u4ec5\u5c71\u4e1c")

tab1, tab2 = st.tabs(["\U0001f4c4 \u4e0a\u4f20PDF\u5fd7\u613f\u8868", "\U0001f4dd \u7c98\u8d34\u5fd7\u613f\u6587\u672c"])

with tab1:
    st.info("\U0001f4a1 \u63a8\u8350\u4f7f\u7528\u5c71\u4e1c\u7701\u6559\u80b2\u62db\u751f\u8003\u8bd5\u9662\u4e0b\u8f7d\u7684\u5b98\u65b9 PDF \u5fd7\u613f\u6587\u4ef6\uff0c\u89e3\u6790\u6700\u51c6\u786e")
    pdf_file = st.file_uploader("\u9009\u62e9 PDF \u6587\u4ef6", type=["pdf"], key="pdf")
    if pdf_file:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as fp:
                fp.write(pdf_file.getvalue()); pp = fp.name
            st.session_state.pdf_vols = parse_pdf(pp)
            os.unlink(pp)
            st.session_state.input_mode = "pdf"
            st.session_state.text_vols = None
            st.success(f"\u2705 \u89e3\u6790\u6210\u529f\uff1a\u5171{len(st.session_state.pdf_vols)}\u4e2a\u5fd7\u613f")
        except:
            st.error("\u274c \u6587\u4ef6\u683c\u5f0f\u65e0\u6cd5\u8bc6\u522b\uff0c\u8bf7\u786e\u8ba4\u662f\u5c71\u4e1c\u7701\u6559\u80b2\u62db\u751f\u8003\u8bd5\u9662\u4e0b\u8f7d\u7684\u5b98\u65b9 PDF\uff0c\u6216\u5207\u6362\u5230\u300c\u7c98\u8d34\u5fd7\u613f\u6587\u672c\u300d\u624b\u52a8\u8f93\u5165\u3002")
with tab2:
    st.info("\U0001f4a1 \u7cbe\u7b80\u683c\u5f0f\uff1a\u6bcf\u884c\u4e00\u4e2a\u300c\u5e8f\u53f7 \u9662\u6821\u4ee3\u7801 \u4e13\u4e1a\u4ee3\u7801\u300d\uff0c\u4f8b\u5982\uff1a\n`1 A558 2Y`\n\u6216\u4ece\u5b98\u65b9 PDF \u76f4\u63a5\u590d\u5236\u7c98\u8d34")
    paste_text = st.text_area("\u5728\u6b64\u7c98\u8d34\u5fd7\u613f\u5185\u5bb9", height=180, key="paste_input", placeholder="\u4f8b\u5982\uff1a\n1 A558 2Y\n2 E880 01\n...")
    if paste_text.strip():
        try:
            st.session_state.text_vols = parse_text(paste_text)
            st.session_state.input_mode = "text"
            st.session_state.pdf_vols = None
            st.success(f"\u2705 \u89e3\u6790\u6210\u529f\uff1a\u5171{len(st.session_state.text_vols)}\u4e2a\u5fd7\u613f")
        except:
            st.error("\u274c \u683c\u5f0f\u65e0\u6cd5\u8bc6\u522b\uff0c\u8bf7\u68c0\u67e5\u5185\u5bb9\u662f\u5426\u6b63\u786e\uff0c\u63a8\u8350\u4f7f\u7528\u7cbe\u7b80\u683c\u5f0f\u3002")

vols = None
if st.session_state.input_mode == "pdf" and st.session_state.pdf_vols:
    vols = st.session_state.pdf_vols
elif st.session_state.input_mode == "text" and st.session_state.text_vols:
    vols = st.session_state.text_vols

rank = st.number_input("\U0001f522 \u4f60\u7684\u7701\u6392\u540d\uff08\u4f4d\u6b21\uff09", min_value=1, step=1, value=None, placeholder="\u4f8b\u5982\uff1a10000\uff0c\u53ef\u5728\u6210\u7ee9\u901a\u77e5\u5355\u6216\u8003\u8bd5\u9662\u5b98\u7f51\u67e5\u770b")
ready = vols is not None and rank is not None and rank > 0

if st.button("\U0001f680 \u5f00\u59cb\u5224\u65ad", type="primary", disabled=not ready):
    lookup = load_data()
    results, matched = judge(rank, lookup, vols)
    st.session_state.last_rank = rank
    st.session_state.last_results = results
    st.session_state.last_matched = matched

if "last_results" in st.session_state and st.session_state.last_results:
    results = st.session_state.last_results
    matched = st.session_state.last_matched
    my_rank = st.session_state.last_rank
    st.divider()

    if matched:
        tr = results[-1]
        st.markdown(
            f"<div style=\"background:#d4edda;border:2px solid #28a745;border-radius:12px;padding:20px;text-align:center;margin:10px 0\">"
            f"<div style=\"font-size:32px;font-weight:700;color:#155724\">\U0001f389 \u547d\u4e2d\uff01</div>"
            f"<div style=\"font-size:20px;color:#155724;margin:10px 0\">\u7b2c {tr['\u5fd7\u613f\u53f7']} \u5fd7\u613f</div>"
            f"<div style=\"font-size:16px;color:#333;margin:4px 0\">\U0001f3eb {tr['\u9662\u6821']}</div>"
            f"<div style=\"font-size:15px;color:#555\">\U0001f4da {tr['\u4e13\u4e1a'][:30]}</div>"
            f"<div style=\"font-size:14px;color:#666;margin-top:6px\">\U0001f4ca \u6700\u4f4e\u4f4d\u6b21 {tr['\u6700\u4f4e\u4f4d\u6b21']:,} / \u4f60\u7684\u4f4d\u6b21 {my_rank:,}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

        hc = 1
        lc = sum(1 for r in results if r["\u7ed3\u679c"] == "\u4f4d\u6b21\u4e0d\u591f")
        nc = sum(1 for r in results if r["\u7ed3\u679c"] == "\u65e0\u5339\u914d")
        with st.expander(f"\U0001f4cb \u67e5\u770b\u5168\u90e8 {len(results)} \u4e2a\u5fd7\u613f\u8be6\u60c5"):
            df = pd.DataFrame(results)
            def hl(r):
                if r["\u7ed3\u679c"] == "\u2705 \u5f55\u53d6":
                    return ["background:#d4edda;font-weight:bold"] * len(r)
                return [""] * len(r)
            st.dataframe(df.style.apply(hl, axis=1), use_container_width=True, hide_index=True)
    else:
        st.error("\u274c \u6240\u6709\u5fd7\u613f\u5747\u672a\u8fbe\u5230\u6700\u4f4e\u6295\u6863\u4f4d\u6b21")
        with st.expander(f"\U0001f4cb \u67e5\u770b\u5168\u90e8 {len(results)} \u4e2a\u5fd7\u613f\u8be6\u60c5"):
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

    if st.button("\U0001f504 \u6362\u4e2a\u6392\u540d\u518d\u8bd5"):
        st.session_state.last_results = None
        st.rerun()

with st.expander("\u2699\ufe0f \u7ba1\u7406\u5458\uff08\u66f4\u65b0\u6295\u6863\u6570\u636e\uff09"):
    pwd = st.text_input("\u7ba1\u7406\u5458\u5bc6\u7801", type="password", key="admin_pwd")
    if pwd == ADMIN_PASSWORD:
        st.success("\u2705 \u9a8c\u8bc1\u901a\u8fc7")
        _t, _y = data_info()
        st.info(f"\U0001f4ca \u5f53\u524d\u53c2\u8003\u6570\u636e\uff1a{_y}\u5e74")
        new_file = st.file_uploader("\u4e0a\u4f20\u65b0\u7684\u6295\u6863\u8868 Excel", type=["xls", "xlsx"], key="admin_excel")
        if new_file:
            with st.spinner("\u6b63\u5728\u5904\u7406..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xls") as fp:
                    fp.write(new_file.getvalue()); ep = fp.name
                try:
                    ext = os.path.splitext(ep)[1].lower()
                    engine = "xlrd" if ext == ".xls" else "openpyxl"
                    df = pd.read_excel(ep, engine=engine, header=None)
                    hr = None
                    for i in range(min(5, len(df))):
                        if str(df.iloc[i, 0]).strip() == "\u4e13\u4e1a\u4ee3\u53f7\u53ca\u540d\u79f0":
                            hr = i; break
                    if hr is None:
                        st.error("\u683c\u5f0f\u9519\u8bef\uff1a\u672a\u627e\u5230\u8868\u5934"); os.unlink(ep)
                    else:
                        new_data = {}
                        for idx in range(hr + 1, len(df)):
                            r = df.iloc[idx]
                            major, school = str(r[0]).strip(), str(r[1]).strip()
                            if not major or major == "nan" or not school or school == "nan": continue
                            sc = school[:4]
                            m = re.match(r"^([A-Za-z0-9]+)", major)
                            if not m: continue
                            mc = m.group(1)
                            try: rk = int(float(r[3]))
                            except: continue
                            key = sc + "|" + mc
                            new_data[key] = min(new_data[key], rk) if key in new_data else rk
                        title_row = str(df.iloc[0, 0]).strip() if len(df) > 0 else ""
                        yr_m = re.search(r"(20\\d{2})", title_row)
                        up_yr = yr_m.group(1) if yr_m else "\u672a\u77e5"
                        st.session_state.custom_data = new_data
                        st.session_state.custom_info = f"\U0001f4ca \u6295\u6863\u6570\u636e\uff1a\u7ba1\u7406\u5458\u4e0a\u4f20\uff08{up_yr}\u5e74\uff0c\u5171{len(new_data)}\u6761\uff09"
                        st.session_state.custom_year = up_yr
                        st.success(f"\u2705 \u6570\u636e\u66f4\u65b0\u6210\u529f\uff01\u5171{len(new_data)}\u6761\u3002\u5f53\u524d\u4f1a\u8bdd\u6709\u6548\u3002\u5982\u9700\u6c38\u4e45\u66f4\u65b0\uff0c\u8bf7\u5728GitHub\u4e0a\u66ff\u6362data.json")
                        st.rerun()
                except Exception as e:
                    st.error(f"\u5904\u7406\u51fa\u9519\uff1a{str(e)}")
                finally:
                    if os.path.exists(ep): os.unlink(ep)
    elif pwd:
        st.error("\u5bc6\u7801\u9519\u8bef")

st.divider()
st.caption("\u26a0\ufe0f \u6570\u636e\u4ec5\u4f9b\u53c2\u8003\uff0c\u7a0b\u5e8f\u53ef\u80fd\u5b58\u5728bug\uff0c\u5177\u4f53\u6295\u6863\u4ee5\u5c71\u4e1c\u7701\u6559\u80b2\u62db\u751f\u8003\u8bd5\u9662\u5b98\u7f51\u53d1\u5e03\u4fe1\u606f\u4e3a\u51c6")
st.caption("\U0001f4a1 \u4ece\u7b2c1\u5fd7\u613f\u4f9d\u6b21\u5224\u65ad\uff0c\u4f60\u7684\u4f4d\u6b21 \u2264 \u8be5\u4e13\u4e1a\u6700\u4f4e\u4f4d\u6b21\u5373\u88ab\u5f55\u53d6\u3002\u6570\u636e\u4ec5\u672c\u6b21\u5904\u7406\uff0c\u4e0d\u4fdd\u5b58\u3002")
