import streamlit as st
import json, os, re, tempfile
import pandas as pd
import pdfplumber

st.set_page_config(page_title="🎫 高考录取辅助查询", page_icon="🎓", layout="centered")
st.markdown("<style>#MainMenu{visibility:hidden}footer{visibility:hidden}</style>", unsafe_allow_html=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin888")
DATA_PATH = "data.json"

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
    for item in vols:
        if len(item) == 5:
            vn, sf, sc, mc, mn = item
            key = sc + "|" + mc
            if key in lookup:
                mr = lookup[key]
                if rank <= mr:
                    results.append({"志愿号": vn, "院校": sf, "专业": mc + mn, "最低位次": mr, "结果": "✅ 录取"})
                    return results, True
                else:
                    results.append({"志愿号": vn, "院校": sf, "专业": (mc + mn)[:20], "最低位次": mr, "结果": "位次不够"})
            else:
                results.append({"志愿号": vn, "院校": sf, "专业": (mc + mn)[:20], "最低位次": "—", "结果": "无匹配"})
        elif len(item) == 3:
            vn, sc, mc = item
            key = sc + "|" + mc
            if key in lookup:
                mr = lookup[key]
                if rank <= mr:
                    results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": mr, "结果": "✅ 录取"})
                    return results, True
                else:
                    results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": mr, "结果": "位次不够"})
            else:
                results.append({"志愿号": vn, "院校": sc, "专业": mc, "最低位次": "—", "结果": "无匹配"})
    return results, False

# ===== UI =====
st.title("🎫 高考录取辅助查询")
st.caption("📍 仅山东")

tab1, tab2 = st.tabs(["📄 上传PDF志愿表", "📝 粘贴志愿文本"])
vols = None

with tab1:
    st.info("💡 推荐使用山东省教育招生考试院下载的官方 PDF 志愿文件")
    pdf_file = st.file_uploader("选择 PDF 文件", type=["pdf"], key="pdf")
    if pdf_file:
        with st.spinner("正在解析PDF..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                f.write(pdf_file.getvalue()); pp = f.name
            try:
                vols = parse_pdf(pp)
                st.success(f"✅ 解析成功：共{len(vols)}个志愿")
            except Exception as e:
                st.error(f"PDF解析失败：{str(e)}")
            os.unlink(pp)

with tab2:
    st.info("💡 精简格式：`1 A558 2Y`，或从官方 PDF 直接复制粘贴")
    paste_text = st.text_area("在此粘贴志愿内容", height=180, key="paste_input", placeholder="例如：\n1 A558 2Y\n2 E880 01\n...")
    if paste_text.strip():
        try:
            vols = parse_text(paste_text)
            st.success(f"✅ 解析成功：共{len(vols)}个志愿")
        except Exception as e:
            st.error(f"解析失败：{str(e)}")

rank = st.number_input("🔢 你的省排名（位次）", min_value=1, step=1, value=None, placeholder="例如：10000")
ready = vols is not None and rank is not None and rank > 0

if st.button("🚀 开始判断", type="primary", disabled=not ready):
    lookup = load_data()
    results, matched = judge(rank, lookup, vols)
    st.divider()
    if matched:
        tr = results[-1]
        v = tr['志愿号']
        st.success(f'🎉 恭喜！你被 **第 {v} 志愿** 录取！')
        a, b, c = st.columns(3)
        a.metric("院校", tr["院校"][:12])
        b.metric("专业", tr["专业"][:12])
        mr = tr['最低位次']
        c.metric('2025最低位次', f'{mr:,}')

    hc = 1 if matched else 0
    lc = sum(1 for r in results if r["结果"] == "位次不够")
    nc = sum(1 for r in results if r["结果"] == "无匹配")
    x, y, z = st.columns(3)
    x.metric("✅ 命中", hc)
    y.metric("位次不够", lc)
    z.metric("无匹配", nc)

    st.subheader("📋 所有志愿详情")
    df = pd.DataFrame(results)

    def hl(r):
        if r["结果"] == "✅ 录取":
            return ["background:#d4edda;font-weight:bold"] * len(r)
        if r["结果"] == "位次不够":
            return ["background:#fff3cd"] * len(r)
        return [""] * len(r)

    st.dataframe(df.style.apply(hl, axis=1), use_container_width=True, hide_index=True)
    if nc > 0:
        st.caption("⚠ 「无匹配」表示该组合未在投档表中找到，可能是当年未招生或代码变化。")

with st.expander("⚙️ 管理员（更新投档数据）"):
    pwd = st.text_input("管理员密码", type="password", key="admin_pwd")
    if pwd == ADMIN_PASSWORD:
        st.success("✅ 验证通过")
        _t, _y = data_info()
        st.info(f"📊 当前参考数据：{_y}年")
        new_file = st.file_uploader("上传新的投档表 Excel", type=["xls", "xlsx"], key="admin_excel")
        if new_file:
            with st.spinner("正在处理..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xls") as fp:
                    fp.write(new_file.getvalue()); ep = fp.name
                try:
                    ext = os.path.splitext(ep)[1].lower()
                    engine = "xlrd" if ext == ".xls" else "openpyxl"
                    df = pd.read_excel(ep, engine=engine, header=None)
                    hr = None
                    for i in range(min(5, len(df))):
                        if str(df.iloc[i, 0]).strip() == "专业代号及名称":
                            hr = i; break
                    if hr is None:
                        st.error("格式错误：未找到表头"); os.unlink(ep)
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
                        up_yr = yr_m.group(1) if yr_m else "未知"
                        st.session_state.custom_data = new_data
                        st.session_state.custom_info = f"📊 投档数据：管理员上传（{up_yr}年，共{len(new_data)}条）"
                        st.session_state.custom_year = up_yr
                        st.success(f"✅ 数据更新成功！共{len(new_data)}条。当前会话有效。如需永久更新，请在GitHub上替换data.json")
                        st.rerun()
                except Exception as e:
                    st.error(f"处理出错：{str(e)}")
                finally:
                    if os.path.exists(ep): os.unlink(ep)
    elif pwd:
        st.error("密码错误")

st.divider()
st.caption("⚠️ 数据仅供参考，程序可能存在bug，具体投档以山东省教育招生考试院官网发布信息为准")
st.caption("💡 从第1志愿依次判断，你的位次 ≤ 该专业最低位次即被录取。数据仅本次处理，不保存。")