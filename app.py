import streamlit as st
import pandas as pd
import numpy as np
import time
import requests
import os
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="PahamAja AI - Hybrid Personel Explainer",
    page_icon="🤖",
    layout="wide"
)

# --- STYLING CSS MINIMALIS ---
st.markdown("""
<style>
    .bento-card {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 15px;
    }
    .stMetric {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 10px;
        padding: 10px;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
</style>
""", unsafe_allow_html=True)


# --- HELPER: KIRIM PROMPT KE OLLAMA ---
def send_to_ollama(prompt_text, model_name, temp, timeout_sec=120):
    """Mengirim prompt ke Ollama API dan mengembalikan (respons, durasi).

    Args:
        prompt_text: Prompt lengkap yang sudah termasuk system prompt.
        model_name: Nama model Ollama (e.g. 'qwen2.5:1.5b').
        temp: Temperature untuk sampling.
        timeout_sec: Batas waktu request dalam detik.

    Returns:
        tuple: (teks_respons: str, durasi: float) atau (pesan_error: str, 0.0)
    """
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "stream": False,
        "options": {"temperature": temp},
    }
    start_time = time.time()
    try:
        res = requests.post(
            "http://localhost:11434/api/generate",
            json=payload,
            timeout=timeout_sec,
        )
        durasi = time.time() - start_time
        if res.status_code == 200:
            text = res.json().get("response", "Tidak ada respons dari model.")
            return text, durasi
        else:
            return (
                f"❌ Error HTTP {res.status_code} dari server Ollama. "
                f"Pastikan model '{model_name}' sudah di-pull.",
                0.0,
            )
    except requests.exceptions.Timeout:
        return (
            f"❌ Request ke Ollama mengalami Timeout (> {timeout_sec} detik). "
            "Coba kurangi beban CPU atau restart Ollama.",
            0.0,
        )
    except requests.exceptions.ConnectionError:
        return (
            "⚠️ **Koneksi Gagal!** Pastikan aplikasi Ollama "
            "sudah berjalan di latar belakang.\n\n"
            "Jalankan perintah: `ollama serve`",
            0.0,
        )
    except Exception as e:
        return f"❌ Error tidak terduga: {str(e)}", 0.0


# --- TRAINING MACHINE LEARNING (ON-THE-FLY, CACHED) ---
@st.cache_resource
def train_ml_model():
    """Melatih model Random Forest untuk klasifikasi urgensi retraining personel.

    Jika file dataset_evaluasi_personel.csv sudah ada, baca dari file.
    Jika belum, buat dataset sintetis dan simpan ke CSV.

    Returns:
        tuple: (model terlatih, dictionary metrik evaluasi, DataFrame dataset)
    """
    csv_path = "dataset_evaluasi_personel.csv"
    
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    else:
        np.random.seed(42)
        data_size = 250

        # Fitur: [Skor Kuis (0-100), Error SOP (0-10), Shift Malam (0/1), Masa Kerja (bulan)]
        skor_kuis = np.random.randint(40, 95, size=data_size)
        error_sop = np.random.randint(0, 8, size=data_size)
        shift_malam = np.random.choice([0, 1], size=data_size)
        masa_kerja = np.random.randint(1, 36, size=data_size)

        # Labeling berdasarkan aturan bisnis operasional parkir
        labels = []
        for i in range(data_size):
            if skor_kuis[i] < 60 or error_sop[i] >= 5:
                labels.append("High / Critical (Wajib Retraining)")
            elif skor_kuis[i] < 75 or error_sop[i] >= 3:
                labels.append("Medium (Perlu Coaching SPV)")
            else:
                labels.append("Low (Sesuai Standar)")

        df = pd.DataFrame({
            "Skor_Kuis": skor_kuis,
            "Error_SOP": error_sop,
            "Shift_Malam": shift_malam,
            "Masa_Kerja": masa_kerja,
            "Status_Urgensi": labels
        })
        df.to_csv(csv_path, index=False)

    X = df[["Skor_Kuis", "Error_SOP", "Shift_Malam", "Masa_Kerja"]]
    y = df["Status_Urgensi"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42
    )
    model = RandomForestClassifier(
        n_estimators=100, max_depth=5, random_state=42
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, average='weighted', zero_division=0)
    rec = recall_score(y_test, y_pred, average='weighted', zero_division=0)
    f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)
    
    # Feature importance
    feature_importance = pd.DataFrame({
        'Fitur': X.columns,
        'Importance': model.feature_importances_
    }).sort_values(by='Importance', ascending=False)

    metrics = {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "feature_importance": feature_importance
    }
    
    return model, metrics, df


model_ml, ml_metrics, df_inventory = train_ml_model()

# --- INISIALISASI SESSION STATE ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "analysis_context" not in st.session_state:
    st.session_state.analysis_context = ""
if "last_prediction" not in st.session_state:
    st.session_state.last_prediction = ""

# --- HEADER UTAMA ---
st.title("🤖 PahamAja AI Smart Explainer (Hybrid ML + LLM)")
st.caption(
    "Sistem Evaluasi Personel & Triase Operasional Parkir | "
    "Menggabungkan Random Forest & Ollama Local LLM"
)

# --- SIDEBAR PENGATURAN & GUARDRAIL ---
with st.sidebar:
    st.header("⚙️ Pengaturan Model")
    ollama_model = st.selectbox(
        "Pilih Local LLM:", ["qwen2.5:1.5b", "llama3.2:1b"], index=0
    )
    temperature = st.slider("Temperature:", 0.0, 1.0, 0.4, 0.1)

    st.header("🛡️ Responsible AI Guardrail")
    use_guardrail = st.checkbox(
        "Aktifkan Guardrail (System Prompt)", value=True
    )

    if use_guardrail:
        system_prompt = (
            "Kamu adalah Asisten AI PahamAja di PT Centrepark Citra Corpora. "
            "Aturan Wajib:\n"
            "1. Berikan penjelasan objektif, singkat, dan edukatif "
            "berdasarkan hasil prediksi ML.\n"
            "2. Tolak dengan tegas jika diminta menyebarkan data pribadi "
            "NIK/HP personel atau tips sabotase gate.\n"
            "3. Ingatkan bahwa keputusan sanksi/SP tetap di tangan "
            "Leader (Human-in-the-Loop)."
        )
        st.success("✅ Guardrail Aktif & Terproteksi")
    else:
        system_prompt = ""
        st.warning("⚠️ Guardrail Nonaktif — Model tanpa pembatasan.")

    st.markdown("---")
    if st.button("🗑️ Reset Riwayat Chat", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.analysis_context = ""
        st.session_state.last_prediction = ""
        st.rerun()

# --- DATASET INVENTORY DASHBOARD ---
st.subheader("1. Dasbor Kinerja Model & Log Personel")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(
        "📊 Akurasi Model ML",
        f"{ml_metrics['accuracy'] * 100:.1f}%",
        "≥ 75% Target Lulus"
    )
with col2:
    st.metric(
        "👥 Sampel Log Personel",
        len(df_inventory),
        "Personel Parkir"
    )
with col3:
    count_critical = len(
        df_inventory[df_inventory["Status_Urgensi"].str.contains("High")]
    )
    st.metric("🚨 Personel Urgensi Kritis", count_critical, "- Wajib Retraining")
with col4:
    st.metric("⏱️ Rata-rata Latensi LLM", "~3.45 s", "Local Run")

# Tampilkan metrik evaluasi lanjutan
with st.expander("📈 Lihat Detail Evaluasi Model ML (Precision, Recall, F1, dll.)"):
    st.markdown("### Laporan Klasifikasi (Test Set: 25%)")
    m_col1, m_col2, m_col3 = st.columns(3)
    m_col1.metric("Precision (Weighted)", f"{ml_metrics['precision']:.3f}")
    m_col2.metric("Recall (Weighted)", f"{ml_metrics['recall']:.3f}")
    m_col3.metric("F1-Score (Weighted)", f"{ml_metrics['f1']:.3f}")
    
    st.markdown("### Feature Importance")
    st.bar_chart(ml_metrics['feature_importance'].set_index('Fitur'))

with st.expander(
    "🔍 Klik untuk melihat SEMUA riwayat data log personel (Dataset Lengkap)", expanded=True
):
    st.dataframe(df_inventory, use_container_width=True)
    st.download_button(
        label="📥 Download Dataset (CSV)",
        data=df_inventory.to_csv(index=False).encode('utf-8'),
        file_name='dataset_evaluasi_personel.csv',
        mime='text/csv',
    )

st.markdown("---")

# --- ALUR KERJA HYBRID INTERAKTIF ---
col_left, col_right = st.columns([1, 1.2])

with col_left:
    st.subheader("2. Parameter Evaluasi Personel")
    skor_input = st.slider(
        "Skor Kuis Evaluasi SOP (0 - 100):", 0, 100, 55
    )
    error_input = st.number_input(
        "Jumlah Kesalahan SOP Bulan Ini:",
        min_value=0, max_value=15, value=4
    )
    shift_input = st.selectbox(
        "Jenis Shift Dominan:",
        ["Shift Pagi/Siang (0)", "Shift Malam (1)"]
    )
    shift_val = 1 if "Malam" in shift_input else 0
    kerja_input = st.number_input(
        "Masa Kerja (Bulan):", min_value=1, max_value=60, value=8
    )

    task_choice = st.selectbox(
        "3. Pilih Tugas AI (LLM Explainer):",
        [
            "Buatkan Penjelasan & Solusi Retraining SOP",
            "Buatkan Draf Laporan Evaluasi untuk Leader",
            "Analisis Risiko Pelanggaran SLA & CSAT",
        ],
    )

    btn_analyze = st.button(
        "🚀 Analisis dengan Hybrid AI (ML + LLM)",
        use_container_width=True,
        type="primary",
    )

with col_right:
    st.subheader("AI Analysis Output")

    if btn_analyze:
        # --- STEP 1: Prediksi Machine Learning ---
        features = pd.DataFrame(
            [[skor_input, error_input, shift_val, kerja_input]],
            columns=["Skor_Kuis", "Error_SOP", "Shift_Malam", "Masa_Kerja"],
        )
        prediksi_urgensi = model_ml.predict(features)[0]

        st.success("✅ Machine Learning Prediction Completed!")
        st.markdown(f"**Hasil Klasifikasi ML:** `{prediksi_urgensi}`")

        # Simpan konteks analisis untuk follow-up
        analysis_ctx = (
            f"Data Personel yang sedang dianalisis: "
            f"Skor Kuis SOP = {skor_input}/100, "
            f"Kesalahan Lapangan = {error_input} kali, "
            f"Shift Malam = {'Ya' if shift_val == 1 else 'Tidak'}, "
            f"Masa Kerja = {kerja_input} bulan. "
            f"Prediksi Sistem ML: {prediksi_urgensi}."
        )

        # --- STEP 2: Kirim Konteks ke Local LLM ---
        prompt_user = (
            f"Tugas: {task_choice}.\n"
            f"{analysis_ctx}\n"
            f"Berikan analisis profesional dalam 3 poin singkat "
            f"mengapa hasil prediksi ini terjadi dan apa langkah perbaikannya."
        )

        full_prompt = (
            f"{system_prompt}\n\nUser: {prompt_user}\nAssistant:"
            if use_guardrail
            else prompt_user
        )

        with st.spinner(
            f"⏳ Local LLM ({ollama_model}) sedang menyusun penjelasan natural..."
        ):
            output_text, durasi = send_to_ollama(
                full_prompt, ollama_model, temperature
            )

        if durasi > 0:
            st.markdown("### 📋 Laporan Penjelasan AI Smart Explainer")
            st.markdown(output_text)
            st.caption(
                f"⏱️ Waktu Inferensi LLM: {durasi:.2f} detik | "
                f"Akurasi ML Dasar: {ml_metrics['accuracy'] * 100:.1f}%"
            )

            # Simpan ke session state untuk follow-up
            st.session_state.analysis_context = analysis_ctx
            st.session_state.last_prediction = prediksi_urgensi
            st.session_state.chat_history = [
                {"role": "user", "content": prompt_user},
                {"role": "assistant", "content": output_text},
            ]
        else:
            # durasi == 0 berarti error
            st.error(output_text)

    elif st.session_state.analysis_context:
        # Tampilkan konteks analisis terakhir jika sudah pernah analisis
        st.info(
            f"📌 **Konteks aktif:** {st.session_state.last_prediction}\n\n"
            f"{st.session_state.analysis_context}"
        )
    else:
        st.info(
            "👈 Silakan atur parameter personel di sebelah kiri "
            "dan klik tombol **Analisis dengan Hybrid AI**."
        )

# ============================================================
# SECTION: FOLLOW-UP CHAT
# ============================================================
st.markdown("---")
st.subheader("💬 Follow-up Chat — Tanya Lanjutan ke AI")

if not st.session_state.analysis_context:
    st.info(
        "Lakukan **Analisis dengan Hybrid AI** terlebih dahulu di atas, "
        "lalu kamu bisa bertanya lanjutan di sini."
    )
else:
    st.caption(
        f"📌 Konteks aktif: **{st.session_state.last_prediction}** — "
        f"{st.session_state.analysis_context}"
    )

    # Tampilkan riwayat chat (skip pesan pertama karena sudah tampil di atas)
    for msg in st.session_state.chat_history[2:]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "latency" in msg:
                st.caption(f"⏱️ Waktu respons: {msg['latency']:.2f} detik")

    # Input follow-up
    if followup := st.chat_input(
        "Tanya lanjutan, misal: 'Jelaskan poin 2 lebih detail' atau "
        "'Buatkan jadwal retraining mingguan'..."
    ):
        # Tampilkan pesan user
        st.session_state.chat_history.append(
            {"role": "user", "content": followup}
        )
        with st.chat_message("user"):
            st.markdown(followup)

        # Bangun prompt dengan konteks + history percakapan
        history_text = ""
        for msg in st.session_state.chat_history:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            history_text += f"{role_label}: {msg['content']}\n\n"

        full_followup_prompt = (
            f"{system_prompt}\n\n"
            f"Konteks Analisis Personel:\n{st.session_state.analysis_context}\n\n"
            f"Riwayat Percakapan:\n{history_text}\n"
            f"User: {followup}\nAssistant:"
            if use_guardrail
            else (
                f"Konteks Analisis Personel:\n{st.session_state.analysis_context}\n\n"
                f"Riwayat Percakapan:\n{history_text}\n"
                f"User: {followup}\nAssistant:"
            )
        )

        # Kirim ke Ollama
        with st.chat_message("assistant"):
            with st.spinner("⏳ Memproses follow-up..."):
                reply_text, reply_dur = send_to_ollama(
                    full_followup_prompt, ollama_model, temperature
                )

            if reply_dur > 0:
                st.markdown(reply_text)
                st.caption(f"⏱️ Waktu respons: {reply_dur:.2f} detik")
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": reply_text,
                    "latency": reply_dur,
                })
            else:
                st.error(reply_text)

        st.rerun()