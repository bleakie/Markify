import json, os, time
import requests

url = "http://0.0.0.0:8562/knowledge_base/doc_parse"
inputs = "./samples"
idlist = os.listdir(inputs)
while 1:
    for id in idlist:
        # time.sleep(5)
        path = f"{inputs}/{id}"
        with open(path, "rb") as file:
            files = {'file_bytes': (file.name, file, 'application/pdf')}
            data = {'file_path': f"/mnt{path}"}  # 如果提供文件路径，可以在这里设置

            response = requests.post(url, files=files, data=data).json()
            if response["code"] != 200:
                print(response["msg"])
