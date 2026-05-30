"""
pipeline/emit.py
Handles event schema + emission to JSONL file and/or API.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

BATCH_SIZE = 100   # events to buffer before flushing to API


class EventEmitter:
    def __init__(self, output_path: str, api_url: Optional[str] = None):
        self.output_path = output_path
        self.api_url = api_url
        self._file = open(output_path, "a", encoding="utf-8")
        self._buffer: list[dict] = []
        self._emitted = 0
        self._client = httpx.Client(timeout=10.0) if api_url else None

    def emit(self, event: dict):
        # Write to JSONL
        self._file.write(json.dumps(event) + "\n")
        self._emitted += 1

        # Buffer for API
        if self.api_url:
            self._buffer.append(event)
            if len(self._buffer) >= BATCH_SIZE:
                self._flush_to_api()

    def _flush_to_api(self):
        if not self._buffer or not self._client:
            return
        try:
            resp = self._client.post(
                f"{self.api_url}/events/ingest",
                json={"events": self._buffer},
            )
            resp.raise_for_status()
            result = resp.json()
            log.info(
                f"API ingest: accepted={result.get('accepted')} "
                f"dup={result.get('duplicate')} rejected={result.get('rejected')}"
            )
        except Exception as e:
            log.error(f"API ingest failed: {e}")
        finally:
            self._buffer.clear()

    def close(self):
        self._flush_to_api()
        self._file.flush()
        self._file.close()
        if self._client:
            self._client.close()
        log.info(f"Emitter closed. Total events emitted: {self._emitted}")
