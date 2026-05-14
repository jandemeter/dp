#!/usr/bin/env python3
from karton.core import Karton, Task, Resource
from mwdblib import MWDB
import requests
import os
import time
import hashlib
import configparser
import json
from datetime import datetime


class Cuckoo3Consumer(Karton):
    identity = "karton.cuckoo3-consumer"
    filters = [
        {
            "type": "sample",
            "stage": "recognized",
            "kind": "runnable"
        }
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Nacitaj konfiguraciu z karton.ini
        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "karton.ini"))

        self.cuckoo_base = config.get("cuckoo", "api_url", fallback="http://127.0.0.1:8091")
        self.cuckoo_token = config.get("cuckoo", "api_token")
        self.cuckoo_headers = {"Authorization": f"token {self.cuckoo_token}"}

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
        filename = sample.name or task.headers.get("filename")

        self.log.info(f"Submitting sample: {filename}")

        # Uloz docasne
        temp_path = f"/tmp/{os.path.basename(filename)}"
        with open(temp_path, "wb") as f:
            f.write(sample.content)

        # Posli do Cuckoo3
        settings = {
            "platforms": [{"platform": "windows", "os_version": "10"}],
            "timeout": 120,
        }

        try:
            with open(temp_path, "rb") as f:
                response = requests.post(
                    f"{self.cuckoo_base}/submit/file",
                    headers=self.cuckoo_headers,
                    files={"file": (os.path.basename(filename), f)},
                    data={"settings": json.dumps(settings)}
                )
            os.remove(temp_path)
        except Exception as e:
            self.log.error(f"Error submitting to Cuckoo3: {e}")
            return

        if response.status_code not in (200, 201):
            self.log.error(f"Cuckoo3 submission failed: {response.status_code} {response.text}")
            return

        analysis_id = response.json().get("analysis_id") or response.json().get("id")
        self.log.info(f"Submitted to Cuckoo3, analysis_id: {analysis_id}")

        # Cakaj na vysledok
        while True:
            try:
                r = requests.get(
                    f"{self.cuckoo_base}/analysis/{analysis_id}",
                    headers=self.cuckoo_headers
                )
                if r.status_code == 404:
                    self.log.error(f"Cuckoo3 analysis {analysis_id} not found")
                    return

                state = r.json().get("state", "")
                self.log.info(f"Cuckoo3 analysis {analysis_id} state: {state}")

                if state == "finished":
                    break
                elif state in ("fatal_error", "aborted"):
                    self.log.error(f"Cuckoo3 analysis {analysis_id} failed: {state}")
                    return

            except Exception as e:
                self.log.error(f"Error polling Cuckoo3: {e}")

            time.sleep(20)

        # Stiahni top-level analyzu
        try:
            r = requests.get(
                f"{self.cuckoo_base}/analysis/{analysis_id}",
                headers=self.cuckoo_headers
            )
            if r.status_code != 200:
                self.log.error(f"Failed to get report: {r.status_code} {r.text}")
                return

            report = r.json()
            self.log.info(f"Got Cuckoo3 top-level report for analysis {analysis_id}")
        except Exception as e:
            self.log.error(f"Error fetching Cuckoo3 report: {e}")
            return

        # Stiahni per-task post report (signatures, network, processes).
        # Top-level /analysis/{id} ma len agregovane info, detaily su v /task/{id}/post.
        post_report = {}
        tasks = report.get("tasks") or []
        if tasks:
            task_id = tasks[0].get("id")
            try:
                r = requests.get(
                    f"{self.cuckoo_base}/analysis/{analysis_id}/task/{task_id}/post",
                    headers=self.cuckoo_headers
                )
                if r.status_code == 200:
                    post_report = r.json()
                    self.log.info(f"Got Cuckoo3 post report for task {task_id}")
                else:
                    self.log.warning(f"Could not get post report: {r.status_code}")
            except Exception as e:
                self.log.error(f"Error fetching post report: {e}")

        # Uloz vysledky do MWDB
        try:
            sha256 = hashlib.sha256(sample.content).hexdigest()

            mwdb_file = self.mwdb.query_file(sha256)

            cuckoo_url = f"http://localhost/analysis/{analysis_id}"

            # Pridaj link na Cuckoo3 analyzu ako atribut
            mwdb_file.add_attribute("cuckoo3-analysis-id", analysis_id)
            mwdb_file.add_attribute("cuckoo3-url", cuckoo_url)

            # State analyzy (finished / fatal_error / aborted)
            state = report.get("state")
            if state:
                mwdb_file.add_attribute("cuckoo3-state", str(state))

            # Kind analyzy
            kind = report.get("kind")
            if kind:
                mwdb_file.add_attribute("cuckoo3-kind", str(kind))

            # Score (0-10)
            score = report.get("score")
            if score is not None:
                mwdb_file.add_attribute("cuckoo3-score", str(score))

            # Malware families
            for family in report.get("families") or []:
                if family:
                    mwdb_file.add_attribute("cuckoo3-family", str(family))
                    try:
                        mwdb_file.add_tag(f"family:{family}")
                    except Exception:
                        pass

            # Tags z analyzy
            for tag in report.get("tags") or []:
                try:
                    mwdb_file.add_tag(f"cuckoo3:{tag}")
                except Exception:
                    pass

            # MITRE ATT&CK TTPs
            seen_ttps = set()
            for ttp_entry in report.get("ttps") or []:
                if isinstance(ttp_entry, dict):
                    ttp_id = ttp_entry.get("id") or ttp_entry.get("ttp")
                else:
                    ttp_id = str(ttp_entry)
                if ttp_id and ttp_id not in seen_ttps:
                    mwdb_file.add_attribute("cuckoo3-ttp", str(ttp_id))
                    seen_ttps.add(ttp_id)

            # Info o nahratej vzorke
            submitted = report.get("submitted") or {}
            if submitted.get("filename"):
                mwdb_file.add_attribute("cuckoo3-filename", submitted["filename"])
            if submitted.get("type"):
                mwdb_file.add_attribute("cuckoo3-filetype", submitted["type"])
            if submitted.get("media_type"):
                mwdb_file.add_attribute("cuckoo3-media-type", submitted["media_type"])

            # Per-task vysledky (Cuckoo3 moze mat viac taskov na rozne platformy)
            for t in tasks:
                if not isinstance(t, dict):
                    continue

                # Duration tasku z ISO 8601 timestamps
                duration_str = ""
                started_on = t.get("started_on")
                stopped_on = t.get("stopped_on")
                if started_on and stopped_on:
                    try:
                        s = datetime.fromisoformat(started_on.replace("Z", "+00:00"))
                        e = datetime.fromisoformat(stopped_on.replace("Z", "+00:00"))
                        duration_seconds = (e - s).total_seconds()
                        duration_str = f" duration={duration_seconds:.1f}s"
                        mwdb_file.add_attribute(
                            "cuckoo3-task-duration",
                            f"{duration_seconds:.1f}s"
                        )
                    except Exception as e:
                        self.log.warning(f"Could not parse task timestamps: {e}")

                task_summary = (
                    f"{t.get('id')} [{t.get('platform')} {t.get('os_version')}] "
                    f"state={t.get('state')} score={t.get('score')}{duration_str}"
                )
                mwdb_file.add_attribute("cuckoo3-task", task_summary)

            # Errors
            errors = report.get("errors") or {}
            if isinstance(errors, dict) and errors:
                mwdb_file.add_attribute("cuckoo3-errors-count", str(len(errors)))

            # Behavioralne signatures (filter podla score >= 5 aby nezahltili MWDB)
            seen_sigs = set()
            for sig in post_report.get("signatures") or []:
                if not isinstance(sig, dict):
                    continue
                sig_score = sig.get("score") or 0
                short_desc = sig.get("short_description") or sig.get("name")
                if not short_desc or short_desc in seen_sigs:
                    continue
                if sig_score >= 5:
                    iocs_count = sig.get("iocs", {}).get("count", 0)
                    sig_text = f"{short_desc} (score={sig_score}, IOCs={iocs_count})"
                    mwdb_file.add_attribute("cuckoo3-signature", sig_text)
                    seen_sigs.add(short_desc)

            # Network IOCs
            network = post_report.get("network") or {}
            if isinstance(network, dict):
                # DNS dotazy
                seen_domains = set()
                for d in network.get("domain") or []:
                    domain = d.get("name") if isinstance(d, dict) else str(d)
                    if domain and domain not in seen_domains:
                        mwdb_file.add_attribute("cuckoo3-domain", domain)
                        seen_domains.add(domain)

                # Host IPs (max 20)
                for ip in (network.get("host") or [])[:20]:
                    if ip:
                        mwdb_file.add_attribute("cuckoo3-host", str(ip))

                # HTTP URL
                seen_urls = set()
                for h in network.get("http") or []:
                    if isinstance(h, dict):
                        url = h.get("url") or h.get("uri")
                        if url and url not in seen_urls:
                            mwdb_file.add_attribute("cuckoo3-http-url", url)
                            seen_urls.add(url)

            # Process info - pocet procesov a hlavny target
            processes = post_report.get("processes") or {}
            if isinstance(processes, dict):
                proc_count = processes.get("count", 0)
                if proc_count:
                    mwdb_file.add_attribute("cuckoo3-process-count", str(proc_count))

                # Najdi target proces (ten s SHA256 prefixom v cmdline)
                sha_prefix = sha256[:16]
                for p in processes.get("process_list") or []:
                    if not isinstance(p, dict):
                        continue
                    cmdline = p.get("commandline") or ""
                    if sha_prefix in cmdline:
                        proc_info = (
                            f"name={p.get('name')} pid={p.get('pid')} "
                            f"state={p.get('state')} "
                            f"duration={(p.get('end_ts') or 0) - (p.get('start_ts') or 0)}ms"
                        )
                        mwdb_file.add_attribute("cuckoo3-target-process", proc_info)

            # Komentar s prehladom
            families = report.get("families") or []
            family_str = ", ".join(families) if families else "none"
            sig_count = len(post_report.get("signatures") or [])
            mwdb_file.add_comment(
                f"Cuckoo3 analysis completed: {cuckoo_url}\n"
                f"  state: {state}\n"
                f"  score: {score}\n"
                f"  families: {family_str}\n"
                f"  ttps: {len(seen_ttps)}\n"
                f"  signatures: {sig_count}\n"
                f"  tasks: {len(tasks)}"
            )

            self.log.info(f"Saved Cuckoo3 results to MWDB for {sha256}")

        except Exception as e:
            self.log.error(f"Error saving to MWDB: {e}")


if __name__ == "__main__":
    Cuckoo3Consumer().loop()
