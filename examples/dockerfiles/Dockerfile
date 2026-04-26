FROM python:3.9

WORKDIR /app

COPY requirements_measurement.txt ./

RUN pip install --upgrade pip
RUN apt-get update && apt-get install -y libgl1-mesa-glx
RUN pip install --no-cache-dir -r requirements_measurement.txt
RUN pip install ipfshttpclient


CMD ["sh", "-c", "python app.py"]
