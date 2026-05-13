#!/usr/bin/env python3
from karton.core import Karton, Task, Resource
from mwdblib import MWDB
import requests
import json
import os
import time
import configparser


class DrakvufConsumer(Karton):
    identity = "karton.drakvuf-consumer"
    filters = [
        {
            "type": "sample",
            "stage": "recognized"
        }
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.drakvuf_base = "http://192.168.122.162:5000"

        # Nacitaj MWDB konfiguraciu z karton.ini
        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "karton.ini"))

        self.mwdb = MWDB(
            api_url=config.get("mwdb", "api_url"),
            api_key=None
        )
        self.mwdb.login(
            username=config.get("mwdb", "username"),
            password=config.get("mwdb", "password")
        )

    def process(self, task: Task):
        sample = task.get_resource("sample")
        filename = task.headers.get("filename", "sample")

        self.log.info(f"Submitting sample: {filename}")

        # Uloz docasne
        temp_path = f"/tmp/{filename}"
        with open(temp_path, "wb") as f:
            f.write(sample.content)

        # Posli do DRAKVUF Sandbox
        # plugins musi byt JSON array string podla API specifikacie
        try:
            with open(temp_path, "rb") as f:
                response = requests.post(
                    f"{self.drakvuf_base}/api/upload",
                    files={"file": (filename, f)},
                    data={
                        "timeout": 600,
                        "plugins": json.dumps(["procmon", "filetracer"]),
                        "no_internet": True,
                        "no_screenshots": True
                    }
                )
            os.remove(temp_path)
        except Exception as e:
            self.log.error(f"Error submitting to DRAKVUF: {e}")
            return

        if response.status_code != 200:
            self.log.error(f"DRAKVUF submission failed: {response.status_code} {response.text}")
            return

        task_uid = response.json().get("task_uid")
        self.log.info(f"Submitted to DRAKVUF, task_uid: {task_uid}")

        if not task_uid:
            self.log.error("DRAKVUF did not return task_uid")
            return

        # Cakaj na vysledok
        while True:
            try:
                r = requests.get(f"{self.drakvuf_base}/api/status/{task_uid}")
                if r.status_code == 404:
                    self.log.error(f"DRAKVUF task {task_uid} not found")
                    return

                data = r.json()
                status = data.get("status")
                self.log.info(f"DRAKVUF task {task_uid} status: {status}")

                if status == "finished":
                    break
                elif status in ("failed", "error"):
                    self.log.error(f"DRAKVUF task {task_uid} failed: {status}")
                    return

            except Exception as e:
                self.log.error(f"Error polling DRAKVUF: {e}")

            time.sleep(30)

        # Uloz vysledky do MWDB
        try:
            mwdb_file = self.mwdb.query_file(sample.sha256)

            drakvuf_url = f"{self.drakvuf_base}/analysis/{task_uid}"

            # Pridaj link na DRAKVUF analyzu ako atribut
            mwdb_file.add_attribute("drakvuf-task-uid", str(task_uid))
            mwdb_file.add_attribute("drakvuf-url", drakvuf_url)

            # Pridaj komentar s linkom
            mwdb_file.add_comment(f"DRAKVUF analysis completed: {drakvuf_url}")

            self.log.info(f"Saved DRAKVUF results to MWDB for {sample.sha256}")

        except Exception as e:
            self.log.error(f"Error saving to MWDB: {e}")


if __name__ == "__main__":
    DrakvufConsumer().loop()
