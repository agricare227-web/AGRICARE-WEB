import streamlit as st
import plotly.graph_objects as go
import streamlit.components.v1 as components
import uuid
import time
import pandas as pd
import io
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

SUPABASE_URL = "https://ewvyvcqaarniauzmgvef.supabase.co"
SUPABASE_KEY = "sb_publishable_XLT4y_7bM4RKMPSsils3kQ_6E3rcDqr"

if "supabase" not in st.session_state:
    st.session_state.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase: Client = st.session_state.supabase

# ID unik per sesi browser -- dipakai buat identifikasi "siapa pegang kunci manual"
if "my_id" not in st.session_state:
    st.session_state.my_id = str(uuid.uuid4())

st.set_page_config(page_title="AgriCare Control Panel", layout="centered")

st.title("🌾 AgriCare Control Panel")
st.write("Smart Precision Spraying — Robotic Arm + Edge AI")

STORAGE_BUCKET = "agricare-history"


def buat_gauge(value, title, unit="", max_val=100, warna="#2E8B57"):
    if value is None:
        value = 0
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={'suffix': f" {unit}"},
        title={'text': title, 'font': {'size': 18}},
        gauge={
            'axis': {'range': [0, max_val]},
            'bar': {'color': warna, 'thickness': 0.3},
            'bgcolor': "white",
            'borderwidth': 0,
            'steps': [
                {'range': [0, max_val * 0.6], 'color': "#e8f5e9"},
                {'range': [max_val * 0.6, max_val * 0.85], 'color': "#fff8e1"},
                {'range': [max_val * 0.85, max_val], 'color': "#ffebee"},
            ],
        }
    ))
    fig.update_layout(height=230, margin=dict(l=15, r=15, t=50, b=15))
    return fig


def baca_csv_dari_storage(nama_file):
    """Ambil CSV dari folder sesi terbaru di Supabase Storage."""
    try:
        files = supabase.storage.from_(STORAGE_BUCKET).list()
        if not files:
            return None, None
        sesi_dirs = sorted(
            [f["name"] for f in files if f["name"].startswith("session_")],
            reverse=True,
        )
        if not sesi_dirs:
            return None, None
        sesi_terbaru = sesi_dirs[0]
        data = supabase.storage.from_(STORAGE_BUCKET).download(
            f"{sesi_terbaru}/{nama_file}"
        )
        return sesi_terbaru, data
    except Exception:
        return None, None


# ============================================================
# FRAGMENT -- bagian ini refresh SENDIRI tiap 5 detik / tiap tombol
# diklik, TANPA memaksa seluruh halaman (termasuk iframe Twitch di
# bawah) ikut digambar ulang. Ini yang mencegah video "kedip mati"
# tiap kali sensor update atau servo/relay dikirim.
# ============================================================
@st.fragment(run_every=5)
def render_dashboard():
    my_id = st.session_state.my_id

    # --- Ambil data terbaru ---
    db_error = None
    try:
        response = supabase.table("kontrol_alat").select(
            "status_relay1, status_relay2, nilai_servo1, nilai_servo2, "
            "suhu_dht22, kelembapan_dht22, suhu_cpu_pi, mode, manual_owner, "
            "last_manual_command_at, sistem_aktif"
        ).eq("id", 1).execute()
        db = response.data[0]
    except Exception as e:
        db_error = str(e)
        db = {
            "status_relay1": False, "status_relay2": False,
            "nilai_servo1": 0.0, "nilai_servo2": 0.0,
            "suhu_dht22": None, "kelembapan_dht22": None, "suhu_cpu_pi": None,
            "mode": "auto", "manual_owner": None, "last_manual_command_at": None,
            "sistem_aktif": False,
        }

    # ============================================================
    # MASTER SWITCH -- SISTEM AKTIF/NONAKTIF
    # Kalau NONAKTIF: scan+spray otomatis tidak akan pernah mulai (dan
    # kalau sedang berjalan, akan dihentikan di posisi/target berikutnya).
    # Kontrol manual & sensor tetap jalan terlepas dari status ini.
    # ============================================================
    st.subheader("🟢 Status Sistem")
    sistem_aktif_sekarang = bool(db.get("sistem_aktif"))

    col_sw1, col_sw2 = st.columns([2, 1])
    with col_sw1:
        if sistem_aktif_sekarang:
            st.success("✅ Sistem AKTIF — siap/sedang menjalankan scan+spray otomatis.")
        else:
            st.warning("⏸️ Sistem NONAKTIF — scan+spray otomatis tidak akan berjalan.")

    with col_sw2:
        toggle_baru = st.toggle(
            "Sistem Aktif",
            value=sistem_aktif_sekarang,
            key="toggle_sistem_aktif",
        )
        if toggle_baru != sistem_aktif_sekarang:
            try:
                supabase.table("kontrol_alat").update({
                    "sistem_aktif": toggle_baru,
                }).eq("id", 1).execute()
                st.rerun(scope="fragment")
            except Exception as e:
                st.error(f"Gagal ubah status sistem: {e}")

    st.divider()

    # --- Banner peringatan sistem ---
    errors_sistem = []
    if db_error:
        errors_sistem.append(f"🔴 <b>Koneksi database gagal</b> — {db_error[:120]}")

    suhu_cpu = db.get("suhu_cpu_pi")
    if suhu_cpu is not None:
        try:
            s = float(suhu_cpu)
            if s > 80:
                errors_sistem.append(
                    f"🔴 <b>Suhu CPU Pi KRITIS: {s}°C</b> — hentikan sistem, risiko thermal throttling / kerusakan."
                )
            elif s > 70:
                errors_sistem.append(
                    f"🟠 <b>Suhu CPU Pi tinggi: {s}°C</b> — pantau terus, pertimbangkan pendinginan tambahan."
                )
        except (ValueError, TypeError):
            pass

    if db.get("suhu_dht22") is None and not db_error:
        errors_sistem.append(
            "🟡 <b>Sensor DHT22 tidak mengirim data</b> — cek wiring sensor / proses di Pi."
        )

    if errors_sistem:
        error_html = "<br><br>".join(errors_sistem)
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
                border-left: 5px solid #ef4444;
                border-radius: 6px;
                padding: 16px 20px;
                margin: 12px 0 20px 0;
            ">
                <div style="color:#fca5a5; font-size:15px; font-weight:700; margin-bottom:10px;">
                    ⚠️ PERINGATAN SISTEM
                </div>
                <div style="color:#fecaca; font-size:14px; line-height:1.7;">
                    {error_html}
                </div>
                <div style="color:#9ca3af; font-size:11px; margin-top:12px;">
                    Banner hilang otomatis saat kondisi normal (dicek ulang tiap 5 detik).
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Gauge sensor ---
    st.subheader("🌱 Kondisi Sensor")
    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        st.plotly_chart(
            buat_gauge(db.get("suhu_dht22"), "Suhu Udara", "°C", max_val=100, warna="#e74c3c"),
            use_container_width=True
        )
    with col_g2:
        st.plotly_chart(
            buat_gauge(db.get("kelembapan_dht22"), "Kelembapan", "%", max_val=100, warna="#3498db"),
            use_container_width=True
        )
    with col_g3:
        st.plotly_chart(
            buat_gauge(db.get("suhu_cpu_pi"), "Suhu CPU Pi", "°C", max_val=100, warna="#f39c12"),
            use_container_width=True
        )

    st.divider()

    # --- Sistem Kunci Manual/Auto ---
    mode = db.get("mode") or "auto"
    manual_owner = db.get("manual_owner")
    i_own_it = (mode == "manual" and manual_owner == my_id)

    st.subheader("🔑 Mode Kendali")
    col_status, col_action = st.columns([2, 1])

    with col_status:
        if mode == "auto":
            st.info("Sistem sedang berjalan otomatis (AUTO).")
        elif i_own_it:
            st.success("Kamu sedang memegang kendali MANUAL. Otomatis lepas kalau 1 menit tidak ada perintah.")
        else:
            st.warning("Sedang dikendalikan MANUAL oleh pengguna lain. Coba lagi sebentar lagi.")

    with col_action:
        if mode == "auto" or not manual_owner:
            if st.button("🔓 Ambil Kendali Manual", use_container_width=True):
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
                claim = supabase.table("kontrol_alat").update({
                    "mode": "manual",
                    "manual_owner": my_id,
                    "last_manual_command_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", 1).or_(f"mode.eq.auto,last_manual_command_at.lt.{cutoff}").execute()

                if claim.data:
                    st.rerun(scope="fragment")
                else:
                    st.warning("Keduluan orang lain, coba lagi.")
        elif i_own_it:
            if st.button("🔒 Lepas Kendali", use_container_width=True):
                supabase.table("kontrol_alat").update({
                    "mode": "auto",
                    "manual_owner": None,
                }).eq("id", 1).eq("manual_owner", my_id).execute()
                st.rerun(scope="fragment")

    st.divider()

    # --- Kendali Hardware ---
    st.header("🔌 Kendali Hardware")
    if not i_own_it:
        st.caption("🔒 Ambil kendali manual dulu di atas untuk mengubah relay/servo.")

    st.subheader("⚙️ Servo Positions (PCA9685)")
    st.caption("Atur posisi arm dulu di sini, baru gunakan tombol Trigger Nozzle di bawah untuk menyemprot dari posisi ini.")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        s1_slider = st.slider("Servo Base (Channel 0) - derajat", min_value=0, max_value=270,
                               value=int(db["nilai_servo1"]), step=1, disabled=not i_own_it)
    with col_s2:
        s2_slider = st.slider("Servo Kamera (Channel 1) - derajat", min_value=0, max_value=270,
                               value=int(db["nilai_servo2"]), step=1, disabled=not i_own_it)

    st.write("")
    if st.button("Kirim Perintah Servo", use_container_width=True, type="primary", disabled=not i_own_it):
        try:
            supabase.table("kontrol_alat").update({
                "nilai_servo1": s1_slider,
                "nilai_servo2": s2_slider,
                "last_manual_command_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", 1).eq("manual_owner", my_id).execute()
            st.success("⚡ Perintah servo berhasil dikirim!")
        except Exception as e:
            st.error(f"Gagal mengirim data: {e}")

    st.divider()

    st.subheader("🔘 Trigger Nozzle")
    st.caption(
        "Klik semprot untuk menembak dari posisi servo SAAT INI (yang sudah diatur di atas). "
        "Sistem otomatis menggeser tilt sesuai offset kamera↔nozzle (9cm) sebelum menembak, "
        "lalu kembali ke posisi kamera semula."
    )

    DURASI_TUNGGU_UI = 3.0

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("💧 Semprot BLAS", use_container_width=True, disabled=not i_own_it):
            try:
                supabase.table("kontrol_alat").update({
                    "manual_spray_label": "BLAS",
                    "last_manual_command_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", 1).execute()
                with st.spinner("Menyemprot BLAS (geser posisi, tembak, kembali)..."):
                    time.sleep(DURASI_TUNGGU_UI)
                st.success("✅ Perintah semprot BLAS terkirim & dieksekusi Pi.")
            except Exception as e:
                st.error(f"Gagal kirim perintah: {e}")

    with col_r2:
        if st.button("💧 Semprot HAWAR DAUN", use_container_width=True, disabled=not i_own_it):
            try:
                supabase.table("kontrol_alat").update({
                    "manual_spray_label": "HAWAR_DAUN",
                    "last_manual_command_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", 1).execute()
                with st.spinner("Menyemprot HAWAR DAUN (geser posisi, tembak, kembali)..."):
                    time.sleep(DURASI_TUNGGU_UI)
                st.success("✅ Perintah semprot HAWAR DAUN terkirim & dieksekusi Pi.")
            except Exception as e:
                st.error(f"Gagal kirim perintah: {e}")

    st.divider()

    # --- Riwayat Sesi Terakhir ---
    st.header("📊 Riwayat Sesi Terakhir")

    tab_deteksi, tab_semprot = st.tabs(["🔍 Hasil Deteksi", "💧 Log Semprot"])

    with tab_deteksi:
        sesi_nama, csv_data = baca_csv_dari_storage("detections.csv")
        if csv_data:
            df = pd.read_csv(io.BytesIO(csv_data))
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Total Deteksi", len(df))
            with c2:
                n_blas = len(df[df["eff_label"] == "BLAS"]) if "eff_label" in df.columns else 0
                st.metric("Blas", n_blas)
            with c3:
                n_hawar = len(df[df["eff_label"] == "HAWAR_DAUN"]) if "eff_label" in df.columns else 0
                st.metric("Hawar Daun", n_hawar)

            st.caption(f"📁 Sesi: **{sesi_nama}**")
            st.dataframe(df, use_container_width=True, height=280)
            st.download_button(
                "⬇️ Unduh detections.csv", data=csv_data,
                file_name=f"{sesi_nama}_detections.csv", mime="text/csv",
                use_container_width=True,
            )
            st.caption(
                "Berisi: sudut servo saat deteksi, label penyakit, confidence YOLO & EfficientNet, "
                "koordinat bounding box, dan koordinat real (cm) dari pusat frame."
            )
        else:
            st.info(
                "📭 **Belum ada data deteksi.**\n\n"
                "Data muncul otomatis setelah: (1) fase scan selesai di Pi, "
                "(2) Pi berhasil mengunggah `detections.csv` ke cloud."
            )

    with tab_semprot:
        sesi_spray, spray_data = baca_csv_dari_storage("spray_log.csv")
        if spray_data:
            df_spray = pd.read_csv(io.BytesIO(spray_data))
            c4, c5 = st.columns(2)
            with c4:
                n_spray = len(df_spray[df_spray["status"] == "sprayed"]) if "status" in df_spray.columns else len(df_spray)
                st.metric("Berhasil Disemprot", n_spray)
            with c5:
                n_skip = len(df_spray[df_spray["status"] != "sprayed"]) if "status" in df_spray.columns else 0
                st.metric("Di-skip", n_skip)

            st.caption(f"📁 Sesi: **{sesi_spray}**")
            st.dataframe(df_spray, use_container_width=True, height=280)
            st.download_button(
                "⬇️ Unduh spray_log.csv", data=spray_data,
                file_name=f"{sesi_spray}_spray_log.csv", mime="text/csv",
                use_container_width=True,
            )
            st.caption(
                "Berisi: ID deteksi terkait, sudut servo saat semprot, nozzle yang dipakai "
                "(B=Blas / C=Hawar Daun), koordinat titik semprot (cm), dan status eksekusi."
            )
        else:
            st.info(
                "📭 **Belum ada log semprot.**\n\n"
                "Data muncul otomatis setelah fase spray selesai dijalankan di Pi."
            )


render_dashboard()

st.divider()

# ============================================================
# LIVE CAMERA STREAM -- SENGAJA DI LUAR fragment di atas, supaya
# iframe TIDAK ikut dibuat ulang tiap 5 detik / tiap tombol diklik.
# Ini yang memperbaiki "video kedip mati" saat servo/relay dikirim.
# ============================================================
st.header("📷 Live Camera Stream")
TWITCH_CHANNEL = "agricare"
PARENT_DOMAIN = "agricare-website.streamlit.app"
components.html(f"""
<iframe src="https://player.twitch.tv/?channel={TWITCH_CHANNEL}&parent={PARENT_DOMAIN}&autoplay=true&muted=true&low_latency=true"
        height="480" width="100%" allowfullscreen></iframe>
""", height=500)
st.caption(
    "⚡ Video diproses langsung di Raspberry Pi (Edge AI) — bounding box digambar sebelum encoding. "
    "Latensi ~3-7 detik adalah karakteristik protokol RTMP; robot **tidak** mengambil keputusan dari stream ini, "
    f"melainkan dari kamera lokal (latensi milidetik). Buka langsung: [twitch.tv/{TWITCH_CHANNEL}](https://twitch.tv/{TWITCH_CHANNEL})"
)
