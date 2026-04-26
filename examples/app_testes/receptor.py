import cv2
import requests
import numpy as np

URL = "http://192.168.70.2/TimeService/video"

stream = requests.get(URL, stream=True)
bytes_buffer = b""

for chunk in stream.iter_content(chunk_size=1024):
    bytes_buffer += chunk
    a = bytes_buffer.find(b"\xff\xd8")  # Início do JPEG
    b = bytes_buffer.find(b"\xff\xd9")  # Fim do JPEG

    if a != -1 and b != -1:
        jpg = bytes_buffer[a:b+2]
        bytes_buffer = bytes_buffer[b+2:]

        img = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)

        if img is not None:
            cv2.imshow("Streaming", img)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

cv2.destroyAllWindows()
