import os
import re
import shutil
import tempfile
from datetime import timedelta
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request as UrlRequest, urlopen

import yt_dlp
from flask import Flask, Response, jsonify, render_template_string, request, send_file

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_download_folder() -> str:
    """Usa una carpeta local si es escribible y cae a /tmp en despliegues serverless."""
    configured = os.environ.get("DOWNLOAD_FOLDER")
    candidates = [
        configured,
        os.path.join(BASE_DIR, "downloads"),
        os.path.join(tempfile.gettempdir(), "video-downloader"),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue

    raise RuntimeError("No se pudo preparar una carpeta temporal para las descargas.")


DOWNLOAD_FOLDER = resolve_download_folder()
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# Plataforma: nombre + ícono (emoji) + etiqueta visual
PLATFORM_RULES = {
    "youtube": {"label": "YouTube", "icon": "▶", "icon_class": "bi bi-youtube", "color": "#ff3131", "domains": ["youtube.com", "youtu.be"]},
    "tiktok": {"label": "TikTok", "icon": "♪", "icon_class": "bi bi-tiktok", "color": "#25f4ee", "domains": ["tiktok.com"]},
    "instagram": {"label": "Instagram", "icon": "◎", "icon_class": "bi bi-instagram", "color": "#fd5949", "domains": ["instagram.com"]},
    "facebook": {"label": "Facebook", "icon": "f", "icon_class": "bi bi-facebook", "color": "#1877f2", "domains": ["facebook.com", "fb.watch"]},
    "x": {"label": "X / Twitter", "icon": "X", "icon_class": "bi bi-twitter-x", "color": "#e5e7eb", "domains": ["twitter.com", "x.com"]},
    "vimeo": {"label": "Vimeo", "icon": "V", "icon_class": "bi bi-vimeo", "color": "#1ab7ea", "domains": ["vimeo.com"]},
}

HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Downloader Pro</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-1: #f6f4ef;
      --bg-2: #f2efe8;
      --bg-3: #ebe7de;
      --card: rgba(255, 255, 255, 0.88);
      --card-soft: rgba(255, 255, 255, 0.7);
      --line: rgba(148, 163, 184, 0.22);
      --text: #17212b;
      --muted: #66707b;
      --accent: #607d74;
      --accent-2: #4f6a62;
      --accent-3: #40554e;
      --success: #22c55e;
      --danger: #fb7185;
      --shadow: 0 20px 50px rgba(15, 23, 42, 0.08);
    }

    body {
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(96, 125, 116, 0.09), transparent 22%),
        radial-gradient(circle at 85% 10%, rgba(79, 106, 98, 0.07), transparent 18%),
        linear-gradient(145deg, var(--bg-1), var(--bg-2) 46%, #f8f6f1 100%);
      color: var(--text);
      font-family: "Manrope", sans-serif;
      overflow-x: hidden;
    }

    .orb {
      position: fixed;
      width: 320px;
      height: 320px;
      border-radius: 50%;
      filter: blur(90px);
      z-index: -1;
      opacity: 0.12;
    }

    .orb-a { top: -120px; left: -120px; background: #8ba59d; }
    .orb-b { bottom: -140px; right: -120px; background: #c8beb0; }

    .app-shell {
      max-width: 1180px;
      margin: 34px auto;
      padding: 0 18px 40px;
      animation: fadeInUp 0.55s ease;
    }

    .panel {
      border: 1px solid var(--line);
      background: var(--card);
      backdrop-filter: blur(14px);
      border-radius: 28px;
      box-shadow: var(--shadow);
    }

    .hero {
      padding: 28px;
      position: relative;
      overflow: hidden;
    }

    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 22px;
      align-items: end;
    }

    .brand-row {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
    }

    .brand-mark {
      width: 56px;
      height: 56px;
      border-radius: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(180deg, rgba(111, 152, 143, 0.2), rgba(71, 103, 97, 0.16));
      border: 1px solid rgba(111, 152, 143, 0.2);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.5);
      color: #406057;
      font-size: 1.4rem;
    }

    .brand-label {
      color: #7d868f;
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 4px;
    }

    .brand-name {
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: -0.03em;
    }

    .title {
      font-size: clamp(1.9rem, 3.2vw, 2.7rem);
      font-weight: 800;
      line-height: 1.06;
      letter-spacing: -0.045em;
      margin-bottom: 10px;
      max-width: 680px;
    }

    .subtitle {
      color: var(--muted);
      margin-bottom: 0;
      max-width: 560px;
      font-size: 0.98rem;
      line-height: 1.65;
    }

    .hero-side {
      padding: 18px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(247, 244, 238, 0.9), rgba(255, 255, 255, 0.78));
      border: 1px solid rgba(148, 163, 184, 0.18);
    }

    .side-label {
      color: #7d868f;
      font-size: 0.76rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 12px;
    }

    .side-title {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 14px;
      color: #27323d;
    }

    .platform-list {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .platform-mini {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(247, 244, 238, 0.95);
      border: 1px solid rgba(148, 163, 184, 0.16);
      color: #36414d;
      font-size: 0.88rem;
      font-weight: 600;
    }

    .platform-mini i {
      color: #607d74;
    }

    .composer {
      margin-top: 20px;
      padding: 16px;
      border-radius: 20px;
      background: rgba(252, 250, 246, 0.92);
      border: 1px solid rgba(148, 163, 184, 0.16);
    }

    .composer-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 140px 180px;
      gap: 14px;
      align-items: end;
    }

    .field-label {
      display: block;
      font-size: 0.84rem;
      font-weight: 700;
      color: #52606d;
      margin-bottom: 8px;
      letter-spacing: 0.02em;
    }

    .input-shell {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 0 16px;
      height: 66px;
      border-radius: 16px;
      background: #ffffff;
      border: 1px solid rgba(148, 163, 184, 0.22);
      transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
    }

    .input-shell:focus-within {
      border-color: rgba(111, 152, 143, 0.42);
      box-shadow: 0 0 0 4px rgba(93, 131, 123, 0.12);
      transform: translateY(-1px);
    }

    .input-shell i {
      color: #607d74;
      font-size: 1.05rem;
    }

    .form-control {
      background: transparent;
      border: 0;
      color: var(--text);
      border-radius: 0;
      padding: 0;
      font-size: 1rem;
      box-shadow: none !important;
    }

    .form-control::placeholder {
      color: #97a1ac;
    }

    .form-select:focus {
      border-color: rgba(111, 152, 143, 0.42);
      box-shadow: 0 0 0 4px rgba(93, 131, 123, 0.12);
      background: rgba(255,255,255,0.06);
      color: var(--text);
    }

    .btn-accent {
      min-height: 66px;
      background: linear-gradient(135deg, #6f988f, #5d837b);
      color: #f4f8f6;
      border: none;
      border-radius: 16px;
      font-weight: 800;
      font-size: 0.96rem;
      transition: transform 0.22s ease, box-shadow 0.22s ease, filter 0.22s ease;
    }

    .btn-accent:hover {
      transform: translateY(-2px);
      box-shadow: 0 16px 28px rgba(71, 103, 97, 0.22);
      filter: saturate(1.03);
      color: #f4f8f6;
    }

    .btn-muted {
      min-height: 66px;
      background: #ffffff;
      color: #3f4c59;
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 16px;
      font-weight: 700;
      font-size: 0.95rem;
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }

    .btn-muted:hover {
      transform: translateY(-1px);
      box-shadow: 0 10px 20px rgba(15, 23, 42, 0.06);
      border-color: rgba(96, 125, 116, 0.26);
      color: #2d3945;
    }

    .preview-wrapper {
      display: none;
      margin-top: 24px;
      padding: 24px;
    }

    .preview-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr);
      gap: 22px;
      align-items: start;
    }

    .media-card,
    .info-card {
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(250,247,242,0.88));
      border: 1px solid rgba(148, 163, 184, 0.16);
      overflow: hidden;
    }

    .media-card {
      --preview-ratio: 16 / 9;
      align-self: start;
    }

    .media-card.is-landscape {
      --preview-ratio: 16 / 9;
    }

    .media-card.is-portrait {
      --preview-ratio: 9 / 16;
      max-width: 420px;
      width: 100%;
      justify-self: center;
    }

    .media-card.is-square {
      --preview-ratio: 1 / 1;
      max-width: 520px;
      width: 100%;
      justify-self: center;
    }

    .media-stage {
      position: relative;
      aspect-ratio: var(--preview-ratio);
      background:
        linear-gradient(180deg, rgba(2,6,23,0.05), rgba(2,6,23,0.35)),
        linear-gradient(135deg, rgba(111, 152, 143, 0.12), rgba(29, 35, 44, 0.08));
    }

    .thumb,
    .embed-frame {
      width: 100%;
      height: 100%;
      aspect-ratio: var(--preview-ratio);
      object-fit: cover;
      border: 0;
    }

    .media-overlay {
      position: absolute;
      inset: auto 18px 18px 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      z-index: 2;
    }

    .overlay-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(4, 12, 24, 0.72);
      border: 1px solid rgba(148, 163, 184, 0.14);
      color: #f8fbff;
      font-size: 0.86rem;
      font-weight: 700;
      backdrop-filter: blur(8px);
    }

    .play-chip {
      width: 54px;
      height: 54px;
      justify-content: center;
      font-size: 1rem;
      cursor: pointer;
      transition: transform 0.2s ease, background 0.2s ease, border-color 0.2s ease, opacity 0.2s ease;
    }

    .play-chip:hover:not(:disabled) {
      transform: translateY(-1px) scale(1.02);
      background: rgba(111, 152, 143, 0.22);
      border-color: rgba(111, 152, 143, 0.3);
    }

    .play-chip:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .play-chip.is-active {
      background: rgba(111, 152, 143, 0.24);
      border-color: rgba(111, 152, 143, 0.34);
    }

    .info-card {
      padding: 22px;
    }

    .platform-row {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
    }

    .platform-logo {
      width: 54px;
      height: 54px;
      border-radius: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(180deg, rgba(247, 244, 238, 0.96), rgba(255,255,255,0.84));
      border: 1px solid rgba(148, 163, 184, 0.2);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
      color: var(--brand, #8fb5ad);
      font-size: 1.55rem;
    }

    .platform-kicker {
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 2px;
    }

    .platform-name {
      font-size: 1.15rem;
      font-weight: 800;
    }

    .meta-title {
      font-size: clamp(1.2rem, 2vw, 1.65rem);
      font-weight: 800;
      margin-bottom: 14px;
      line-height: 1.35;
    }

    .meta-stack {
      display: grid;
      gap: 10px;
      margin-bottom: 18px;
    }

    .meta-pill {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(248, 246, 241, 0.95);
      border: 1px solid rgba(148, 163, 184, 0.16);
      color: var(--muted);
      font-size: 0.94rem;
    }

    .meta-pill i {
      color: #8fb5ad;
    }

    .control-card {
      margin-top: 18px;
      padding: 16px;
      border-radius: 20px;
      background: rgba(248, 246, 241, 0.95);
      border: 1px solid rgba(148, 163, 184, 0.16);
    }

    .quality-note {
      display: none;
      margin-bottom: 14px;
      padding: 11px 12px;
      border-radius: 14px;
      background: rgba(96, 125, 116, 0.08);
      border: 1px solid rgba(96, 125, 116, 0.16);
      color: #52665f;
      font-size: 0.86rem;
      line-height: 1.45;
    }

    .quality-note.is-visible {
      display: block;
    }

    .form-select {
      min-height: 54px;
      background: #ffffff;
      border: 1px solid rgba(148, 163, 184, 0.2);
      color: var(--text);
      border-radius: 16px;
      margin-bottom: 14px;
    }

    .history-card {
      margin-top: 18px;
      padding: 16px;
      border-radius: 20px;
      background: rgba(252, 250, 246, 0.92);
      border: 1px solid rgba(148, 163, 184, 0.16);
    }

    .history-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }

    .history-title {
      font-size: 0.95rem;
      font-weight: 800;
      color: #24303b;
    }

    .history-clear {
      border: 0;
      background: transparent;
      color: #7a8692;
      font-size: 0.88rem;
      font-weight: 700;
      padding: 0;
    }

    .history-clear:hover {
      color: #41505d;
    }

    .history-list {
      display: grid;
      gap: 10px;
    }

    .history-item {
      display: grid;
      grid-template-columns: 42px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      appearance: none;
      width: 100%;
      text-align: left;
      padding: 12px;
      border-radius: 16px;
      border: 1px solid rgba(148, 163, 184, 0.16);
      background: #ffffff;
      color: #24303b;
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }

    .history-item:hover {
      transform: translateY(-1px);
      box-shadow: 0 12px 20px rgba(15, 23, 42, 0.05);
      border-color: rgba(96, 125, 116, 0.24);
    }

    .history-icon {
      width: 42px;
      height: 42px;
      border-radius: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: rgba(248, 246, 241, 0.95);
      border: 1px solid rgba(148, 163, 184, 0.16);
      font-size: 1rem;
    }

    .history-text {
      min-width: 0;
    }

    .history-name {
      display: block;
      font-size: 0.9rem;
      font-weight: 700;
      color: #24303b;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-bottom: 2px;
    }

    .history-url {
      display: block;
      font-size: 0.8rem;
      color: #7a8692;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .history-empty {
      padding: 14px;
      border-radius: 16px;
      background: rgba(248, 246, 241, 0.9);
      border: 1px dashed rgba(148, 163, 184, 0.22);
      color: #7a8692;
      font-size: 0.88rem;
    }

    .status {
      margin-top: 14px;
      padding: 13px 15px;
      border-radius: 14px;
      font-size: 0.95rem;
      display: none;
      animation: fadeInUp 0.3s ease;
    }

    .status.loading { display: block; background: rgba(111, 152, 143, 0.1); border: 1px solid rgba(111, 152, 143, 0.22); color: #395149; }
    .status.error { display: block; background: rgba(251, 113, 133, 0.1); border: 1px solid rgba(251, 113, 133, 0.22); color: #8b3d4e; }
    .status.success { display: block; background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.22); color: #356648; }

    .loader {
      width: 18px;
      height: 18px;
      border: 2px solid rgba(255,255,255,0.35);
      border-top-color: #fff;
      border-radius: 50%;
      display: inline-block;
      animation: spin 0.85s linear infinite;
      margin-right: 8px;
      vertical-align: -3px;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 991px) {
      .app-shell {
        margin: 20px auto;
        padding: 0 14px 28px;
      }

      .panel,
      .hero,
      .preview-wrapper {
        border-radius: 24px;
      }

      .hero,
      .preview-wrapper {
        padding: 22px;
      }

      .hero-grid,
      .preview-grid,
      .composer-row {
        grid-template-columns: 1fr;
      }

      .hero-side {
        padding: 16px;
      }

      .title {
        max-width: none;
        font-size: clamp(1.8rem, 7vw, 2.75rem);
      }

      .subtitle {
        font-size: 0.98rem;
        line-height: 1.65;
      }

      .composer {
        padding: 14px;
        border-radius: 20px;
      }

      .field-label {
        margin-bottom: 8px;
      }

      .btn-accent,
      .input-shell {
        min-height: 58px;
        height: auto;
      }

      .preview-grid {
        gap: 18px;
      }

      .media-card,
      .info-card,
      .control-card {
        border-radius: 20px;
      }

      .thumb,
      .embed-frame,
      .media-stage {
        min-height: 0;
      }

      .meta-title {
        font-size: 1.3rem;
      }
    }

    @media (max-width: 767px) {
      .orb {
        width: 260px;
        height: 260px;
        filter: blur(80px);
      }

      .app-shell {
        margin: 14px auto;
        padding: 0 10px 22px;
      }

      .panel,
      .hero,
      .preview-wrapper {
        border-radius: 20px;
      }

      .hero,
      .preview-wrapper {
        padding: 16px;
      }

      .hero-side {
        padding: 14px;
        border-radius: 18px;
      }

      .brand-row {
        margin-bottom: 14px;
      }

      .brand-mark {
        width: 50px;
        height: 50px;
        border-radius: 16px;
      }

      .brand-name {
        font-size: 1.16rem;
      }

      .side-title {
        font-size: 0.94rem;
        margin-bottom: 12px;
      }

      .platform-list {
        grid-template-columns: 1fr 1fr;
        gap: 8px;
      }

      .platform-mini {
        padding: 9px 10px;
        font-size: 0.82rem;
      }

      .composer {
        margin-top: 18px;
        padding: 12px;
        border-radius: 18px;
      }

      .composer-row {
        gap: 10px;
      }

      .input-shell {
        min-height: 56px;
        padding: 0 14px;
        border-radius: 16px;
      }

      .btn-accent {
        min-height: 56px;
        border-radius: 16px;
        font-size: 0.96rem;
      }

      .btn-muted {
        min-height: 56px;
        border-radius: 16px;
      }

      .preview-grid {
        gap: 14px;
      }

      .media-card,
      .info-card,
      .control-card {
        border-radius: 18px;
      }

      .media-stage,
      .thumb,
      .embed-frame {
        min-height: 0;
      }

      .media-card.is-portrait,
      .media-card.is-square {
        max-width: 100%;
      }

      .media-overlay {
        inset: auto 12px 12px 12px;
        gap: 8px;
      }

      .overlay-chip {
        padding: 8px 10px;
        font-size: 0.78rem;
      }

      .play-chip {
        width: 46px;
        height: 46px;
      }

      .info-card {
        padding: 16px;
      }

      .platform-row {
        gap: 12px;
        margin-bottom: 14px;
      }

      .platform-logo {
        width: 48px;
        height: 48px;
        border-radius: 14px;
        font-size: 1.35rem;
      }

      .platform-name {
        font-size: 1.02rem;
      }

      .meta-title {
        font-size: 1.12rem;
        margin-bottom: 12px;
      }

      .meta-stack {
        gap: 8px;
        margin-bottom: 14px;
      }

      .meta-pill {
        align-items: flex-start;
        padding: 10px 12px;
        font-size: 0.88rem;
      }

      .meta-pill span {
        line-height: 1.45;
        word-break: break-word;
      }

      .control-card {
        margin-top: 14px;
        padding: 12px;
      }

      .form-select {
        min-height: 50px;
        border-radius: 14px;
        font-size: 0.92rem;
      }

      .status {
        padding: 12px 13px;
        font-size: 0.9rem;
      }

      .history-card {
        margin-top: 14px;
        padding: 12px;
      }
    }

    @media (max-width: 479px) {
      .title {
        font-size: 1.65rem;
      }

      .subtitle {
        font-size: 0.92rem;
      }

      .platform-list {
        grid-template-columns: 1fr;
      }

      .platform-row {
        align-items: flex-start;
      }

      .overlay-chip:first-child {
        max-width: calc(100% - 58px);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }
  </style>
</head>
<body>
  <div class="orb orb-a"></div>
  <div class="orb orb-b"></div>

  <main class="app-shell">
    <section class="panel hero">
      <div class="hero-grid">
        <div>
          <div class="brand-row">
            <div class="brand-mark">
              <i class="bi bi-arrow-down-circle"></i>
            </div>
            <div>
              <div class="brand-label">App</div>
              <div class="brand-name">VideoDownloader</div>
            </div>
          </div>
          <h1 class="title">Descarga videos desde un enlace en segundos.</h1>
          <p class="subtitle">Pega la URL, revisa la vista previa y elige la calidad disponible.</p>
        </div>

        <div class="hero-side">
          <div class="side-label">Compatible con</div>
          <div class="side-title">YouTube, TikTok, Instagram, Facebook, X y Vimeo</div>
          <div class="platform-list">
            <div class="platform-mini"><i class="bi bi-youtube"></i>YouTube</div>
            <div class="platform-mini"><i class="bi bi-tiktok"></i>TikTok</div>
            <div class="platform-mini"><i class="bi bi-instagram"></i>Instagram</div>
            <div class="platform-mini"><i class="bi bi-facebook"></i>Facebook</div>
            <div class="platform-mini"><i class="bi bi-twitter-x"></i>X</div>
            <div class="platform-mini"><i class="bi bi-vimeo"></i>Vimeo</div>
          </div>
        </div>
      </div>

      <div class="composer">
        <div class="composer-row">
          <div>
            <label class="field-label">URL del video</label>
            <div class="input-shell">
              <i class="bi bi-link-45deg"></i>
              <input id="videoUrl" class="form-control form-control-lg" type="url" placeholder="Pega aquí el enlace del video..." autocomplete="off">
            </div>
          </div>
          <div class="d-grid">
            <label class="field-label">&nbsp;</label>
            <button id="pasteBtn" class="btn btn-muted btn-lg" type="button">
              <i class="bi bi-clipboard me-2"></i>
              Pegar
            </button>
          </div>
          <div class="d-grid">
            <label class="field-label">&nbsp;</label>
            <button id="previewBtn" class="btn btn-accent btn-lg">
              <i class="bi bi-magic me-2"></i>
              Analizar URL
            </button>
          </div>
        </div>
      </div>

      <div class="history-card">
        <div class="history-head">
          <div class="history-title">Historial reciente</div>
          <button id="clearHistoryBtn" class="history-clear" type="button">Limpiar</button>
        </div>
        <div id="historyList" class="history-list"></div>
      </div>

      <div id="status" class="status"></div>
    </section>

    <section id="previewCard" class="panel preview-wrapper">
      <div class="preview-grid">
        <div id="mediaCard" class="media-card">
          <div class="media-stage">
            <img id="thumb" class="thumb" alt="thumbnail" src="">
            <div class="media-overlay">
              <div id="platformBadge" class="overlay-chip">Plataforma detectada</div>
              <button id="playPreviewBtn" type="button" class="overlay-chip play-chip" aria-label="Reproducir vista previa" disabled>
                <i class="bi bi-play-fill"></i>
              </button>
            </div>
          </div>
          <iframe id="videoEmbed" class="embed-frame" style="display:none;" src="" title="video preview" allowfullscreen></iframe>
        </div>

        <div class="info-card">
          <div class="platform-row">
            <div id="platformLogo" class="platform-logo"><i class="bi bi-globe2"></i></div>
            <div>
              <div class="platform-kicker">Plataforma detectada</div>
              <div id="platformName" class="platform-name">Video social</div>
            </div>
          </div>

          <div id="videoTitle" class="meta-title"></div>
          <div class="meta-stack">
            <div id="videoUploader" class="meta-pill"><i class="bi bi-person-circle"></i><span></span></div>
            <div id="videoDuration" class="meta-pill"><i class="bi bi-clock-history"></i><span></span></div>
            <div id="videoOrigin" class="meta-pill"><i class="bi bi-globe-americas"></i><span></span></div>
          </div>

          <div class="control-card">
            <label class="field-label">Calidad disponible</label>
            <select id="qualitySelect" class="form-select"></select>
            <div id="qualityNote" class="quality-note"></div>
            <button id="downloadBtn" class="btn btn-accent btn-lg w-100">
              <i class="bi bi-download me-2"></i>
              Descargar Video
            </button>
          </div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const videoUrlInput = document.getElementById('videoUrl');
    const pasteBtn = document.getElementById('pasteBtn');
    const previewBtn = document.getElementById('previewBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const playPreviewBtn = document.getElementById('playPreviewBtn');
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    const historyList = document.getElementById('historyList');
    const previewCard = document.getElementById('previewCard');
    const mediaCard = document.getElementById('mediaCard');
    const platformBadge = document.getElementById('platformBadge');
    const platformLogo = document.getElementById('platformLogo');
    const platformName = document.getElementById('platformName');
    const thumb = document.getElementById('thumb');
    const videoEmbed = document.getElementById('videoEmbed');
    const videoTitle = document.getElementById('videoTitle');
    const videoUploader = document.getElementById('videoUploader');
    const videoDuration = document.getElementById('videoDuration');
    const videoOrigin = document.getElementById('videoOrigin');
    const qualitySelect = document.getElementById('qualitySelect');
    const qualityNote = document.getElementById('qualityNote');
    const statusBox = document.getElementById('status');
    const HISTORY_KEY = 'video_downloader_history';
    let currentPreview = { embedUrl: '', webpageUrl: '', isPlaying: false };
    const fallbackThumb = 'data:image/svg+xml;utf8,' + encodeURIComponent(`
      <svg xmlns="http://www.w3.org/2000/svg" width="900" height="500" viewBox="0 0 900 500">
        <defs>
          <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#0f172a"/>
            <stop offset="100%" stop-color="#1e293b"/>
          </linearGradient>
        </defs>
        <rect width="900" height="500" fill="url(#g)"/>
        <circle cx="450" cy="250" r="68" fill="#22d3ee" opacity="0.22"/>
        <polygon points="430,214 430,286 494,250" fill="#67e8f9"/>
        <text x="450" y="340" fill="#e2e8f0" text-anchor="middle" font-family="Arial,sans-serif" font-size="22">
          Preview no disponible
        </text>
      </svg>
    `);

    function setStatus(type, message) {
      statusBox.className = 'status ' + type;
      if (type === 'loading') {
        statusBox.innerHTML = '<span class="loader"></span>' + message;
      } else {
        statusBox.textContent = message;
      }
    }

    function clearStatus() {
      statusBox.className = 'status';
      statusBox.textContent = '';
    }

    function getSafeUrl() {
      return (videoUrlInput.value || '').trim();
    }

    function readHistory() {
      try {
        return JSON.parse(window.localStorage.getItem(HISTORY_KEY) || '[]');
      } catch (error) {
        return [];
      }
    }

    function writeHistory(items) {
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
    }

    function renderHistory() {
      const items = readHistory();
      historyList.innerHTML = '';

      if (!items.length) {
        historyList.innerHTML = '<div class="history-empty">Aun no hay enlaces guardados. Analiza un video y aparecera aqui.</div>';
        return;
      }

      items.forEach((item, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'history-item';
        button.dataset.index = String(index);
        button.innerHTML = `
          <span class="history-icon" style="color:${item.color || '#607d74'}">
            <i class="${item.icon_class || 'bi bi-clock-history'}"></i>
          </span>
          <span class="history-text">
            <span class="history-name">${item.title || item.host || 'Video reciente'}</span>
            <span class="history-url">${item.url}</span>
          </span>
        `;
        button.addEventListener('click', () => {
          videoUrlInput.value = item.url || '';
          fetchPreview();
        });
        historyList.appendChild(button);
      });
    }

    function saveHistoryItem(item) {
      const currentItems = readHistory().filter((entry) => entry.url !== item.url);
      currentItems.unshift(item);
      writeHistory(currentItems.slice(0, 6));
      renderHistory();
    }

    function withAutoplay(url) {
      if (!url) return '';
      const separator = url.includes('?') ? '&' : '?';
      return `${url}${separator}autoplay=1`;
    }

    function setPreviewLayout(layout) {
      mediaCard.classList.remove('is-landscape', 'is-portrait', 'is-square');
      const normalized = ['landscape', 'portrait', 'square'].includes(layout) ? layout : 'landscape';
      mediaCard.classList.add(`is-${normalized}`);
    }

    function resetPlayer() {
      currentPreview.isPlaying = false;
      videoEmbed.style.display = 'none';
      videoEmbed.src = '';
      thumb.style.display = 'block';
      playPreviewBtn.classList.remove('is-active');
      playPreviewBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
      playPreviewBtn.setAttribute('aria-label', 'Reproducir vista previa');
    }

    function activatePlayer() {
      if (currentPreview.embedUrl) {
        currentPreview.isPlaying = true;
        videoEmbed.style.display = 'block';
        videoEmbed.src = withAutoplay(currentPreview.embedUrl);
        thumb.style.display = 'none';
        playPreviewBtn.classList.add('is-active');
        playPreviewBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
        playPreviewBtn.setAttribute('aria-label', 'Cerrar reproductor');
        return;
      }

      if (currentPreview.webpageUrl) {
        window.open(currentPreview.webpageUrl, '_blank', 'noopener,noreferrer');
        setStatus('success', 'Esta plataforma no permite embed directo. Abrí el video original en otra pestaña.');
        return;
      }

      setStatus('error', 'No hay una vista previa reproducible disponible para este video.');
    }

    function togglePlayer() {
      if (currentPreview.isPlaying) {
        resetPlayer();
        return;
      }
      activatePlayer();
    }

    async function handlePaste() {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        setStatus('error', 'Tu navegador no permite leer el portapapeles desde esta pagina.');
        return;
      }

      try {
        const clipboardText = (await navigator.clipboard.readText()).trim();
        if (!clipboardText) {
          setStatus('error', 'El portapapeles esta vacio.');
          return;
        }
        videoUrlInput.value = clipboardText;
        setStatus('success', 'Enlace pegado desde el portapapeles.');
      } catch (error) {
        setStatus('error', 'No se pudo leer el portapapeles. Revisa los permisos del navegador.');
      }
    }

    async function fetchPreview() {
      const url = getSafeUrl();
      if (!url) {
        setStatus('error', 'Ingresa una URL válida para continuar.');
        return;
      }

      setStatus('loading', 'Obteniendo metadata del video...');
      previewCard.style.display = 'none';

      try {
        const response = await fetch('/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });

        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || 'No se pudo procesar la URL.');
        }

        platformBadge.innerHTML = `<i class="${data.platform.icon_class}"></i> ${data.platform.label}`;
        platformLogo.style.setProperty('--brand', data.platform.color || '#7dd3fc');
        platformLogo.innerHTML = `<i class="${data.platform.icon_class}"></i>`;
        platformName.textContent = data.platform.label;
        setPreviewLayout(data.preview_layout);
        currentPreview = {
          embedUrl: data.embed_url || '',
          webpageUrl: data.url || '',
          isPlaying: false
        };
        playPreviewBtn.disabled = !currentPreview.embedUrl && !currentPreview.webpageUrl;
        resetPlayer();
        thumb.style.display = 'block';
        thumb.src = data.thumbnail_proxy || fallbackThumb;
        thumb.onerror = () => {
          thumb.onerror = null;
          thumb.src = fallbackThumb;
        };
        videoTitle.textContent = data.title || 'Título no disponible';
        videoUploader.querySelector('span').textContent = data.uploader || 'Creador no disponible';
        videoDuration.querySelector('span').textContent = data.duration || 'Duración no disponible';
        videoOrigin.querySelector('span').textContent = data.host || 'Origen no disponible';
        saveHistoryItem({
          url: data.url,
          title: data.title || data.host || 'Video',
          host: data.host || '',
          icon_class: data.platform.icon_class,
          color: data.platform.color
        });

        qualitySelect.innerHTML = '';
        data.qualities.forEach((q) => {
          const opt = document.createElement('option');
          opt.value = q.format_id;
          opt.textContent = q.label;
          qualitySelect.appendChild(opt);
        });

        if (!data.ffmpeg_available && data.platform.key === 'youtube') {
          qualityNote.classList.add('is-visible');
          qualityNote.textContent = 'En YouTube, 720p/1080p suelen venir en video y audio separados. Como ffmpeg no esta instalado en este entorno, solo se muestran calidades compatibles, por eso normalmente el maximo visible es 360p.';
        } else {
          qualityNote.classList.remove('is-visible');
          qualityNote.textContent = '';
        }

        previewCard.style.display = 'block';
        setStatus('success', 'Vista previa cargada. Selecciona calidad y descarga.');
      } catch (error) {
        setStatus('error', error.message || 'Error inesperado al obtener la vista previa.');
      }
    }

    async function handleDownload() {
      const url = getSafeUrl();
      const formatId = qualitySelect.value;

      if (!url || !formatId) {
        setStatus('error', 'Primero analiza una URL y elige una calidad.');
        return;
      }

      setStatus('loading', 'Preparando descarga...');

      try {
        const response = await fetch('/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, format_id: formatId })
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({ error: 'No se pudo iniciar la descarga.' }));
          throw new Error(data.error || 'No se pudo iniciar la descarga.');
        }

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);

        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = match ? match[1] : 'video_descargado.mp4';

        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();

        window.URL.revokeObjectURL(downloadUrl);
        setStatus('success', 'Descarga completada correctamente.');
      } catch (error) {
        setStatus('error', error.message || 'Error al descargar el video.');
      }
    }

    function clearHistory() {
      window.localStorage.removeItem(HISTORY_KEY);
      renderHistory();
      setStatus('success', 'Historial eliminado.');
    }

    renderHistory();
    pasteBtn.addEventListener('click', handlePaste);
    previewBtn.addEventListener('click', fetchPreview);
    downloadBtn.addEventListener('click', handleDownload);
    playPreviewBtn.addEventListener('click', togglePlayer);
    clearHistoryBtn.addEventListener('click', clearHistory);

    videoUrlInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        fetchPreview();
      }
    });

    videoUrlInput.addEventListener('input', () => {
      if (statusBox.classList.contains('error')) {
        clearStatus();
      }
    });
  </script>
</body>
</html>
"""


def is_valid_url(url: str) -> bool:
    """Valida si la URL tiene esquema y dominio aceptables."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def detect_platform(url: str) -> dict:
    """Detecta plataforma usando el dominio de la URL."""
    netloc = urlparse(url).netloc.lower().replace("www.", "")
    for key, meta in PLATFORM_RULES.items():
        if any(domain in netloc for domain in meta["domains"]):
            return {
                "key": key,
                "label": meta["label"],
                "icon": meta["icon"],
                "icon_class": meta["icon_class"],
                "color": meta["color"],
            }
    return {
        "key": "unknown",
        "label": "Plataforma no identificada",
        "icon": "o",
        "icon_class": "bi bi-globe2",
        "color": "#7dd3fc",
    }


def format_host(url: str) -> str:
    """Devuelve el host limpio para mostrarlo en la UI."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    return host or "origen-desconocido"


def format_seconds(seconds: Optional[int]) -> str:
    """Convierte segundos en HH:MM:SS o MM:SS."""
    if not seconds:
        return "No disponible"
    td = timedelta(seconds=int(seconds))
    total = int(td.total_seconds())
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_quality_label(fmt: dict) -> str:
    """Construye una etiqueta legible de calidad."""
    height = fmt.get("height") or "?"
    ext = (fmt.get("ext") or "mp4").upper()
    fps = fmt.get("fps")
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    with_audio = fmt.get("acodec") not in (None, "none")

    label = f"{height}p · {ext}"
    if fps:
        label += f" · {int(fps)}fps"
    if size:
        label += f" · {round(size / (1024 * 1024), 1)}MB"
    if with_audio:
        label += " · audio"
    return label


def score_format(fmt: dict) -> tuple:
    """Prioriza formatos con audio, mayor fps y mayor tamano estimado."""
    has_audio = fmt.get("acodec") not in (None, "none")
    fps = fmt.get("fps") or 0
    size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
    return (1 if has_audio else 0, fps, size)


def pick_best_thumbnail(info: dict) -> Optional[str]:
    """Selecciona la mejor miniatura disponible del extractor."""
    direct_thumb = info.get("thumbnail")
    if direct_thumb:
        return direct_thumb

    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return None

    valid = [t for t in thumbs if t.get("url")]
    if not valid:
        return None

    # Priorizamos mayor resolución cuando esté disponible.
    valid.sort(key=lambda t: (t.get("height") or 0, t.get("width") or 0), reverse=True)
    return valid[0].get("url")


def build_thumbnail_proxy_url(thumbnail_url: Optional[str], page_url: Optional[str] = None) -> Optional[str]:
    """Genera una URL local para servir la miniatura a traves de Flask."""
    if not thumbnail_url:
        return None
    proxy_url = f"/thumbnail?src={quote(thumbnail_url, safe='')}"
    if page_url:
        proxy_url += f"&page={quote(page_url, safe='')}"
    return proxy_url


def detect_preview_layout(platform_key: str, info: dict) -> str:
    """Determina la proporcion visual mas adecuada para el preview."""
    width = info.get("width")
    height = info.get("height")

    if width and height:
        ratio = width / height
        if ratio >= 1.15:
            return "landscape"
        if ratio <= 0.85:
            return "portrait"
        return "square"

    if platform_key in {"tiktok"}:
        return "portrait"
    if platform_key in {"instagram"}:
        return "square"
    return "landscape"


def extract_video_info(url: str) -> dict:
    """Obtiene metadata y calidades disponibles desde yt-dlp sin descargar."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Si llega playlist/colección, tomamos la primera entrada.
    if info and "entries" in info and isinstance(info["entries"], list) and info["entries"]:
        info = info["entries"][0]

    formats = info.get("formats") or []
    selected_formats = {}

    for fmt in formats:
        fmt_id = fmt.get("format_id")
        vcodec = fmt.get("vcodec")
        ext = fmt.get("ext")
        height = fmt.get("height")
        has_audio = fmt.get("acodec") not in (None, "none")

        if not fmt_id or not height or vcodec in (None, "none"):
            continue
        if ext not in {"mp4", "webm", "mkv"}:
            continue
        if not FFMPEG_AVAILABLE and not has_audio:
            continue

        # Mostramos una sola opcion por resolucion/extension, priorizando audio integrado.
        key = (height, ext)
        current = selected_formats.get(key)
        if current is None or score_format(fmt) > score_format(current):
            selected_formats[key] = fmt

    usable_formats = [
        {
            "format_id": fmt.get("format_id"),
            "height": fmt.get("height"),
            "label": build_quality_label(fmt),
            "has_audio": fmt.get("acodec") not in (None, "none"),
            "ext": fmt.get("ext"),
        }
        for fmt in selected_formats.values()
    ]

    usable_formats.sort(key=lambda item: item["height"])

    if not usable_formats:
        # Fallback: opción automática si no pudimos listar formatos visuales
        fallback_label = "Mejor calidad disponible"
        if not FFMPEG_AVAILABLE:
            fallback_label = "Mejor calidad compatible"
        usable_formats = [{"format_id": "best", "height": 0, "label": fallback_label, "has_audio": True, "ext": "mp4"}]

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel") or "No disponible",
        "duration": format_seconds(info.get("duration")),
        "width": info.get("width"),
        "height": info.get("height"),
        "thumbnail": pick_best_thumbnail(info),
        "webpage_url": info.get("webpage_url") or url,
        "ffmpeg_available": FFMPEG_AVAILABLE,
        "qualities": usable_formats,
    }


def extract_youtube_embed(url: str, video_id: Optional[str]) -> Optional[str]:
    """Construye URL de embed para YouTube cuando sea posible."""
    if video_id:
        return f"https://www.youtube.com/embed/{video_id}"

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "youtu.be" in host:
        vid = parsed.path.strip("/")
        return f"https://www.youtube.com/embed/{vid}" if vid else None

    query = parse_qs(parsed.query)
    vid = query.get("v", [None])[0]
    return f"https://www.youtube.com/embed/{vid}" if vid else None


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ffmpeg_available": FFMPEG_AVAILABLE})


@app.route("/thumbnail", methods=["GET"])
def thumbnail_proxy():
    """Sirve la miniatura desde el backend para evitar bloqueos de carga en el navegador."""
    src = (request.args.get("src") or "").strip()
    page = (request.args.get("page") or "").strip()
    if not is_valid_url(src):
        return jsonify({"ok": False, "error": "Miniatura invalida."}), 400

    remote_request = UrlRequest(
        src,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": page if is_valid_url(page) else src,
        },
    )

    try:
        with urlopen(remote_request, timeout=12) as remote_response:
            content = remote_response.read()
            content_type = remote_response.headers.get("Content-Type", "image/jpeg").split(";")[0]

        response = Response(content, mimetype=content_type)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response
    except (HTTPError, URLError, TimeoutError):
        return jsonify({"ok": False, "error": "No se pudo cargar la miniatura."}), 502


@app.route("/preview", methods=["POST"])
def preview():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()

    if not is_valid_url(url):
        return jsonify({"ok": False, "error": "URL inválida. Verifica el enlace e intenta de nuevo."}), 400

    platform = detect_platform(url)

    try:
        info = extract_video_info(url)
        embed_url = extract_youtube_embed(info.get("webpage_url") or url, info.get("id")) if platform["key"] == "youtube" else None
        preview_layout = detect_preview_layout(platform["key"], info)

        return jsonify(
            {
                "ok": True,
                "url": info.get("webpage_url") or url,
                "host": format_host(info.get("webpage_url") or url),
                "platform": platform,
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "thumbnail_proxy": build_thumbnail_proxy_url(info.get("thumbnail"), info.get("webpage_url") or url),
                "embed_url": embed_url,
                "preview_layout": preview_layout,
                "ffmpeg_available": info.get("ffmpeg_available", False),
                "qualities": info.get("qualities", []),
            }
        )
    except yt_dlp.utils.DownloadError as exc:
        return jsonify({"ok": False, "error": f"No se pudo procesar esta URL: {str(exc)}"}), 400
    except Exception:
        return jsonify({"ok": False, "error": "Ocurrió un error inesperado al analizar la URL."}), 500


@app.route("/download", methods=["POST"])
def download():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    format_id = (payload.get("format_id") or "").strip()

    if not is_valid_url(url):
        return jsonify({"ok": False, "error": "URL inválida para descargar."}), 400

    if not format_id:
        return jsonify({"ok": False, "error": "Selecciona una calidad antes de descargar."}), 400

    temp_dir = tempfile.mkdtemp(prefix="video_dl_", dir=DOWNLOAD_FOLDER)
    output_template = os.path.join(temp_dir, "%(title).120s.%(ext)s")

    # Intentamos primero el formato exacto; si no está disponible, caemos a best.
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": output_template,
        "restrictfilenames": True,
    }

    if FFMPEG_AVAILABLE:
        ydl_opts["format"] = f"{format_id}+bestaudio/{format_id}/best" if format_id != "best" else "best"
        ydl_opts["merge_output_format"] = "mp4"
    else:
        ydl_opts["format"] = format_id if format_id != "best" else "best[acodec!=none][vcodec!=none]/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_file = ydl.prepare_filename(info)

        if not os.path.exists(final_file):
            # Algunos extractores cambian extensión tras merge/post-proc.
            candidate_files = [
                os.path.join(temp_dir, f)
                for f in os.listdir(temp_dir)
                if re.search(r"\.(mp4|webm|mkv|mov)$", f, flags=re.IGNORECASE)
            ]
            if candidate_files:
                final_file = candidate_files[0]
            else:
                raise FileNotFoundError("No se generó el archivo final de descarga.")

        response = send_file(final_file, as_attachment=True)

        @response.call_on_close
        def cleanup_temp() -> None:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return response
    except yt_dlp.utils.DownloadError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": f"Error de descarga: {str(exc)}"}), 400
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": "No se pudo completar la descarga."}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    app.run(host="0.0.0.0", port=port, debug=debug)
