import os
import time
import cv2
import streamlit as st

st.set_page_config(layout="wide")

st.title("AgriCare Robot Dashboard")

placeholder = st.empty()

IMAGE_PATH = "../output_latest.jpg"

while True:

    if os.path.exists(IMAGE_PATH):

        frame = cv2.imread(IMAGE_PATH)

        if frame is not None:

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            placeholder.image(
                frame,
                channels="RGB",
                use_container_width=True
            )

    time.sleep(0.05)
