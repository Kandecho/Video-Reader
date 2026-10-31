"""Explicitly enabled native AV reader. No external config or credential discovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from filelock import FileLock

from .common import ReaderError, UNTRUSTED, read_json, write_json
from .reader import Reader, _watch_call, print_progress
from .vendor import gemini


class Cloud:
    def __init__(self, reader: Reader):
        self.reader = reader
        if not reader.config["gemini"]["enabled"]:
            raise ReaderError("Gemini is disabled. Local reading is the default. Explicitly enable gemini.enabled in this component's config.json to use cloud tools.")
        self.key = os.environ.get(reader.config["gemini"]["api_key_env"], "").strip()
        if not self.key:
            raise ReaderError("Native AV requires the explicitly configured API key environment variable")
        self.model = reader.config["gemini"]["model"]

    def _request(self, method, url, payload=None):
        kwargs = {"timeout": 40}
        if payload is not None:
            kwargs.update(data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        _, _, body = _watch_call(gemini._call, method, url, self.key, **kwargs)
        try:
            return json.loads(body)
        except ValueError:
            raise ReaderError("Native AV returned invalid JSON") from None

    def ask(self, session, question):
        if not question.strip():
            raise ReaderError("Question must not be empty")
        if not session.startswith("v_"):
            session = self.reader.register_youtube(session)
        directory = self.reader.directory(session)
        with FileLock(str(directory / ".lock"), timeout=600):
            data = self.reader.load(session)
            path = directory / "cloud.json"
            state = read_json(path) if path.is_file() else {"history": []}
            if pending := state.get("pending"):
                if pending["question"] != question:
                    raise ReaderError("A native AV question is still running; poll it before starting another")
                return self._result(state, session)
            if previous := state.get("previous_interaction_id"):
                if state["model"] != self.model:
                    raise ReaderError("Model changed during the cloud session; close it before using a new model")
                inputs = [{"type": "text", "text": gemini.build_prompt(question) + "\n" + UNTRUSTED}]
            else:
                if data["source"]["platform"] == "youtube":
                    video = {"uri": data["source"]["canonical"]}
                else:
                    upload = state.get("upload")
                    if upload and time.time() - state.get("uploaded_at", 0) > 47 * 3600:
                        upload = None
                    if not upload:
                        print_progress("Uploading video for native audiovisual understanding")
                        upload = _watch_call(gemini.upload_file, Path(data["media_path"]), self.key, max_wait=180)
                        state.update(upload=upload, uploaded_at=time.time())
                        write_json(path, state)
                    video = {k: upload[k] for k in ("uri", "mime_type")}
                inputs = [{"type": "video", **video, "processing": self.reader.config["gemini"]["processing"]},
                          {"type": "text", "text": gemini.build_prompt(question) + "\n" + UNTRUSTED}]
            payload = {"model": self.model, "input": inputs, "background": True, "store": True}
            if previous:
                payload["previous_interaction_id"] = previous
            # Do not retry POST after an ambiguous network failure: it could bill twice.
            response = self._request("POST", gemini.INTERACTIONS, payload)
            if not response.get("id"):
                raise ReaderError("Native AV did not return an interaction id")
            state.update(model=self.model, pending={"id": response["id"], "question": question,
                                                   "started_at": time.time()}, last_response=response)
            state.pop("error", None)
            self._finish(state, response)
            write_json(path, state)
            return self._result(state, session)

    def poll(self, session):
        directory = self.reader.directory(session)
        with FileLock(str(directory / ".lock"), timeout=600):
            path = directory / "cloud.json"
            if not path.is_file():
                raise ReaderError("No native AV interaction exists for this session")
            state = read_json(path)
            if pending := state.get("pending"):
                # GET is safe to repeat after a broken connection; interaction id survives process restarts.
                response = self._request("GET", gemini.INTERACTIONS + "/" + pending["id"])
                state["last_response"] = response
                self._finish(state, response)
                write_json(path, state)
            return self._result(state, session)

    def _finish(self, state, response):
        status = response.get("status")
        if status == "completed":
            parts = [part["text"] for step in response.get("steps", []) if step.get("type") == "model_output"
                     for part in step.get("content", []) if part.get("type") == "text" and part.get("text")]
            answer = "\n".join(parts).strip() or response.get("output_text", "")
            state["history"].append({"question": state["pending"]["question"], "answer": answer,
                                     "interaction_id": response["id"], "usage": response.get("usage")})
            state["previous_interaction_id"] = response["id"]
            state.pop("pending", None)
        elif status in ("failed", "cancelled", "incomplete"):
            state["error"] = {"status": status, "detail": response.get("error")}
            state.pop("pending", None)

    def _result(self, state, session):
        pending = state.get("pending")
        response = state.get("last_response", {})
        return {"session_id": session, "status": response.get("status", "unknown"), "model": state.get("model"),
                "interaction_id": pending["id"] if pending else state.get("previous_interaction_id"),
                "answer": state["history"][-1]["answer"] if not pending and state["history"] and response.get("status") == "completed" else None,
                "error": state.get("error"), "next_tool": "video_cloud_poll" if pending else None,
                "observed_by": "Gemini native audiovisual model", "source_content_policy": UNTRUSTED}

    def close(self, session):
        directory = self.reader.directory(session)
        with FileLock(str(directory / ".lock"), timeout=600):
            path = directory / "cloud.json"
            if not path.is_file():
                return {"status": "closed", "session_id": session}
            state = read_json(path)
            if state.get("pending"):
                raise ReaderError("Native AV interaction is still running; poll it before closing")
            warning = gemini.delete_file(state["upload"]["name"], self.key) if state.get("upload") else None
            if warning:
                return {"status": "cleanup_failed", "session_id": session, "warning": warning}
            history = state.get("history", [])
            write_json(directory / f"cloud-history-{time.time_ns()}.json", history)
            path.unlink()
            return {"status": "closed", "session_id": session,
                    "remote_file_deleted": bool(state.get("upload")), "local_evidence_preserved": True}
