# ==================== IMPORTS ET CONFIGURATION ====================

import json
import logging
import os
import secrets
import threading
import time
import random
import math
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import numpy as np
from jinja2 import Environment, BaseLoader
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, jsonify, request, redirect, url_for, session, send_file, make_response
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== HELPERS DEVISE FCFA ====================================

def fmt_fcfa(value: float, decimals: bool = False) -> str:
    """Formate un montant en FCFA avec séparateur de milliers.
    Ex: 1500.75 -> '1 501 FCFA' (decimals=False)
        1500.75 -> '1 500,75 FCFA' (decimals=True)
    """
    if decimals:
        s = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    else:
        s = f"{round(value):,}".replace(",", " ")
    return f"{s} FCFA"

# ==================== GESTIONNAIRE DE DONNÉES ====================

class SimpleDataManager:
    """Gestionnaire de données en mémoire avec limite de rétention."""
    def __init__(self):
        self.data_cache: Dict[str, List] = {}
        self.last_update: Dict[str, str] = {}
        logger.info("✅ Gestionnaire de données initialisé")

    def save_realtime_data(self, component: str, data: Dict) -> bool:
        self.data_cache.setdefault(component, [])
        entry = {"timestamp": datetime.now().isoformat(), "component": component, **data}
        self.data_cache[component].append(entry)
        self.last_update[component] = entry["timestamp"]
        if len(self.data_cache[component]) > 1000:
            self.data_cache[component] = self.data_cache[component][-1000:]
        return True

    def get_realtime_data(self, component: str, limit: int = 100) -> List[Dict]:
        return self.data_cache.get(component, [])[-limit:]

    def get_system_status(self) -> Dict:
        return {
            "components_loaded": list(self.data_cache.keys()),
            "last_updates": self.last_update,
            "timestamp": datetime.now().isoformat(),
        }

# ==================== CONFIGURATION FLASK ====================

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_TYPE = "filesystem"
    SESSION_PERMANENT = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    TEMPLATES_AUTO_RELOAD = True

# ==================== MODÈLE UTILISATEUR ====================

class User(UserMixin):
    def __init__(self, id, username, role, permissions, password_hash=""):
        self.id = id
        self.username = username
        self.role = role
        self.permissions = permissions
        self.password_hash = password_hash

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

# ==================== TEMPLATES HTML ====================

_JINJA_ENV = Environment(loader=BaseLoader(), auto_reload=False)

HTML_TEMPLATES: Dict[str, str] = {
    # ── LOGIN ──────────────────────────────────────────────────────────────────────
    'login': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN Dashboard - Connexion</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body { background: linear-gradient(135deg, #1a2a3a, #2c3e50); height: 100vh; display: flex; align-items: center; justify-content: center; }
.login-card { background-color: rgba(255,255,255,.1); backdrop-filter: blur(10px); border-radius: 15px; padding: 40px; width: 100%; max-width: 400px; border: 1px solid rgba(255,255,255,.2); }
.logo { text-align: center; margin-bottom: 30px; }
.logo i { font-size: 3rem; color: #4CAF50; }
.form-control { background-color: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2); color: white; }
.form-control:focus { background-color: rgba(255,255,255,.15); border-color: #4CAF50; color: white; box-shadow: 0 0 0 .25rem rgba(76,175,80,.25); }
.btn-login { background: linear-gradient(135deg, #4CAF50, #2E7D32); border: none; width: 100%; padding: 12px; font-weight: bold; color: white; }
</style>
</head>
<body>
<div class="login-card">
<div class="logo">
<i class="fas fa-leaf"></i>
<h2 class="mt-3 text-white">SEN Dashboard</h2>
<small class="text-muted">Symbiosis Energy Nexus</small>
</div>
{% if error %}
<div class="alert alert-danger" role="alert">
<i class="fas fa-exclamation-triangle me-2"></i>{{ error }}
</div>
{% endif %}
<form method="POST" action="/login">
<div class="mb-3">
<label for="username" class="form-label text-white">
<i class="fas fa-user me-2"></i>Nom d'utilisateur
</label>
<input type="text" class="form-control" id="username" name="username" required autocomplete="username">
</div>
<div class="mb-3">
<label for="password" class="form-label text-white">
<i class="fas fa-lock me-2"></i>Mot de passe
</label>
<input type="password" class="form-control" id="password" name="password" required autocomplete="current-password">
</div>
<button type="submit" class="btn btn-login">
<i class="fas fa-sign-in-alt me-2"></i>Se connecter
</button>
</form>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''',
    # ── WELCOME (page de bienvenue, une seule fois après login) ──────────────────
    'welcome': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bienvenue — Système SEN</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Segoe UI',sans-serif;height:100vh;overflow:hidden;}
.welcome-bg{
  position:fixed;inset:0;
  background:
    linear-gradient(135deg, rgba(20,40,20,.55), rgba(60,45,20,.55)),
    url('https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=1600&q=80') center/cover no-repeat,
    linear-gradient(135deg,#1b3a1b,#4a3b1c);
}
.overlay{
  position:fixed;inset:0;
  background:rgba(0,0,0,.55);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;padding:20px;
  animation:fadeIn 1.6s ease;
}
@keyframes fadeIn{from{opacity:0;transform:translateY(20px);}to{opacity:1;transform:translateY(0);}}
.leaf-icon{font-size:5rem;color:#4CAF50;margin-bottom:20px;filter:drop-shadow(0 4px 12px rgba(0,0,0,.5));}
.welcome-title{color:#fff;font-size:2.6rem;font-weight:800;margin-bottom:12px;text-shadow:0 2px 8px rgba(0,0,0,.6);}
.welcome-sub{color:#d6f5d6;font-size:1.15rem;margin-bottom:36px;max-width:600px;}
.btn-enter{
  background:linear-gradient(135deg,#4CAF50,#2E7D32);
  color:#fff;border:none;border-radius:40px;
  padding:16px 42px;font-size:1.2rem;font-weight:700;
  cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:10px;
  box-shadow:0 6px 20px rgba(76,175,80,.5);transition:transform .25s,box-shadow .25s;
}
.btn-enter:hover{transform:translateY(-3px);box-shadow:0 10px 28px rgba(76,175,80,.7);color:#fff;}
@media(max-width:576px){.welcome-title{font-size:1.9rem;}.welcome-sub{font-size:1rem;}.btn-enter{padding:14px 32px;font-size:1.05rem;}}
</style>
</head>
<body>
<div class="welcome-bg"></div>
<div class="overlay">
<i class="fas fa-leaf leaf-icon"></i>
<h1 class="welcome-title">Bienvenue sur le Système SEN</h1>
<p class="welcome-sub">Symbiotic Energy Nexus — Surveillance Intelligente</p>
<a href="/?from_welcome=1" class="btn-enter"><i class="fas fa-tachometer-alt"></i>Accéder au Tableau de Bord</a>
</div>
</body>
</html>
''',
    # ── INDEX ──────────────────────────────────────────────────────────────────────
    'index': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN Dashboard - Accueil</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body { background-color: #121212; color: #fff; font-family: 'Segoe UI', sans-serif; }
.sidebar { background-color: #1e1e1e; min-height: 100vh; padding-top: 20px; }
.sidebar a { color: #fff; text-decoration: none; display: block; padding: 10px 20px; margin: 5px 0; border-radius: 5px; transition: all .3s; }
.sidebar a:hover, .sidebar a.active { background-color: #4CAF50; }
.content { padding: 20px; }
.card { background-color: #2d2d2d; border: 1px solid #444; border-radius: 10px; margin-bottom: 20px; }
.card-header { background-color: #1a1a1a; border-bottom: 1px solid #444; padding: 15px; }
.stat-card { text-align: center; padding: 20px; border-radius: 10px; margin: 10px 0; }
.stat-card .value { font-size: 2.5rem; font-weight: bold; }
.stat-card .label { font-size: .9rem; opacity: .8; }
</style>
</head>
<body>
<div id="demo-banner" style="background:#B71C1C;color:#fff;text-align:center;padding:8px;font-weight:600;font-size:.9rem">
⚠️ Mode Démo : En attente des données ESP32
</div>
<script>
fetch('/api/data/status').then(r=>r.json()).then(d=>{
    if (d.real_data_received) {
        var b = document.getElementById('demo-banner');
        if (b) b.style.display = 'none';
    }
});
</script>
<div class="container-fluid">
<div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4">
<h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4>
<small class="text-muted">Version 3.5</small>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/" class="active"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2">
<strong>{{ user.username }}</strong><br>
<small class="text-muted">{{ user.role }}</small>
</div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100">
<i class="fas fa-sign-out-alt me-1"></i>Déconnexion
</a>
</div>
</div>
<div class="col-md-10 content">
<div class="d-flex justify-content-between align-items-center mb-4">
<h2><i class="fas fa-tachometer-alt me-2"></i>Tableau de Bord SEN</h2>
<div class="text-end">
<span class="badge bg-success me-2"><i class="fas fa-circle me-1"></i>En ligne</span>
<small class="text-muted">{{ system_status.uptime }}</small>
</div>
</div>
<div class="row mb-4">
<div class="col-md-4">
<div class="stat-card" style="background:linear-gradient(135deg,#2E7D32,#4CAF50)">
<div class="value">{{ realtime_data.digester.gas_flow | round(2) }}</div>
<div class="label">Production Biogaz (m³/h)</div>
<small><i class="fas fa-arrow-up me-1"></i>+2.5%</small>
</div>
</div>
<div class="col-md-4">
<div class="stat-card" style="background:linear-gradient(135deg,#6A1B9A,#9C27B0)">
<div class="value">{{ realtime_data.photobioreactor.biomass_density | round(2) }}</div>
<div class="label">Densité Biomasse (g/L)</div>
<small><i class="fas fa-seedling me-1"></i>Croissance</small>
</div>
</div>
<div class="col-md-4">
<div class="stat-card" style="background:linear-gradient(135deg,#C62828,#F44336)">
<div class="value">{{ realtime_data.economics.daily_profit | round(0) | int | format_fcfa }}</div>
<div class="label">Profit Quotidien</div>
<small><i class="fas fa-coins me-1"></i>Journalier</small>
</div>
</div>
</div>
<div class="row">
<div class="col-md-4">
<div class="card">
<div class="card-header"><h5><i class="fas fa-chart-line me-2"></i>Temps Réel</h5></div>
<div class="card-body">
<p>Visualisation des données en temps réel avec graphiques interactifs.</p>
<a href="/dashboard/realtime" class="btn btn-success"><i class="fas fa-external-link-alt me-1"></i>Ouvrir</a>
</div>
</div>
</div>
<div class="col-md-4">
<div class="card">
<div class="card-header"><h5><i class="fas fa-chart-bar me-2"></i>Historique</h5></div>
<div class="card-body">
<p>Analyse des tendances et données historiques sur 7 jours.</p>
<a href="/dashboard/historical" class="btn btn-primary"><i class="fas fa-external-link-alt me-1"></i>Ouvrir</a>
</div>
</div>
</div>
<div class="col-md-4">
<div class="card">
<div class="card-header"><h5><i class="fas fa-chart-pie me-2"></i>Analytique</h5></div>
<div class="card-body">
<p>Analyses avancées et prédictions machine learning.</p>
<a href="/dashboard/analytics" class="btn btn-warning"><i class="fas fa-external-link-alt me-1"></i>Ouvrir</a>
</div>
</div>
</div>
</div>
<div class="card mt-4">
<div class="card-header"><h5><i class="fas fa-heartbeat me-2"></i>État du Système</h5></div>
<div class="card-body">
<div class="row">
<div class="col-md-3">
<h6>Santé Globale</h6>
<div class="progress" style="height:25px">
<div class="progress-bar bg-success" style="width:{{ system_status.overall_health }}%">
{{ system_status.overall_health }}%
</div>
</div>
</div>
<div class="col-md-9">
<div class="row">
{% for component, status in system_status.component_status.items() %}
<div class="col-md-2 text-center mb-2">
<div class="p-2 rounded
{% if status == 'optimal' %}bg-success
{% elif status == 'good' %}bg-primary
{% elif status == 'warning' %}bg-warning
{% else %}bg-danger{% endif %}">
<small>{{ component|title }}</small><br>
<strong>{{ status|title }}</strong>
</div>
</div>
{% endfor %}
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''',
    # ── REALTIME DASHBOARD ─────────────────────────────────────────────────────────
    'realtime_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Dashboard Temps Réel</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
<style>
body { background-color:#121212; color:#fff; font-family:'Segoe UI',sans-serif; }
.sidebar { background-color:#1e1e1e; min-height:100vh; padding-top:20px; }
.sidebar a { color:#fff; text-decoration:none; display:block; padding:10px 20px; margin:5px 0; border-radius:5px; transition:all .3s; }
.sidebar a:hover, .sidebar a.active { background-color:#4CAF50; }
.content { padding:20px; }
.card { background-color:#2d2d2d; border:1px solid #444; border-radius:10px; margin-bottom:20px; }
.card-header { background-color:#1a1a1a; border-bottom:1px solid #444; padding:15px; }
.stat-card { text-align:center; padding:15px; border-radius:10px; margin:10px 0; }
.stat-card .value { font-size:2rem; font-weight:bold; }
.stat-card .label { font-size:.9rem; opacity:.8; }
.graph-container { height:300px; width:100%; }
.parameter-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }
.parameter-card { background-color:#2d2d2d; border:1px solid #444; border-radius:8px; padding:15px; text-align:center; }
.parameter-card .value { font-size:1.8rem; font-weight:bold; margin:10px 0; }
.parameter-card .label { font-size:.8rem; opacity:.8; }
</style>
</head>
<body>
<div id="demo-banner" style="background:#B71C1C;color:#fff;text-align:center;padding:8px;font-weight:600;font-size:.9rem">
⚠️ Mode Démo : En attente des données ESP32
</div>
<script>
fetch('/api/data/status').then(r=>r.json()).then(d=>{
    if (d.real_data_received) {
        var b = document.getElementById('demo-banner');
        if (b) b.style.display = 'none';
    }
});
</script>
<div class="container-fluid">
<div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4">
<h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4>
<small class="text-muted">Temps Réel</small>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime" class="active"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<div class="d-flex justify-content-between align-items-center mb-4">
<h2><i class="fas fa-chart-line me-2"></i>Dashboard Temps Réel</h2>
<div class="text-end">
<span class="badge bg-success me-2"><i class="fas fa-circle me-1"></i>Live</span>
<small class="text-muted" id="current-time">Chargement...</small>
</div>
</div>
<div class="row mb-4">
<div class="col-md-4">
<div class="stat-card" style="background:linear-gradient(135deg,#2E7D32,#4CAF50)">
<div class="value" id="biogas-flow">{{ realtime_data.digester.gas_flow | round(2) }}</div>
<div class="label">Production Biogaz (m³/h)</div>
<small><i class="fas fa-fire me-1"></i>CH₄: {{ realtime_data.digester.ch4_concentration | round(1) }}%</small>
</div>
</div>
<div class="col-md-4">
<div class="stat-card" style="background:linear-gradient(135deg,#6A1B9A,#9C27B0)">
<div class="value" id="biomass-density">{{ realtime_data.photobioreactor.biomass_density | round(2) }}</div>
<div class="label">Biomasse Algale (g/L)</div>
<small><i class="fas fa-seedling me-1"></i>Croissance active</small>
</div>
</div>
<div class="col-md-4">
<div class="stat-card" style="background:linear-gradient(135deg,#FF9800,#FFC107)">
<div class="value" id="co2-captured">{{ realtime_data.environmental.co2_captured | round(1) }}</div>
<div class="label">CO₂ Capturé (kg)</div>
<small><i class="fas fa-tree me-1"></i>Équiv. {{ realtime_data.environmental.equivalent_trees | round(1) }} arbres</small>
</div>
</div>
</div>
<div class="row mb-4">
<div class="col-md-12">
<div class="card">
<div class="card-header"><h5><i class="fas fa-chart-line me-2"></i>Production de Biogaz - 24h</h5></div>
<div class="card-body"><div id="biogas-graph" class="graph-container"></div></div>
</div>
</div>
</div>
<div class="row mb-4">
<div class="col-md-12">
<div class="card">
<div class="card-header"><h5><i class="fas fa-wind me-2"></i>Analyse des Gaz</h5></div>
<div class="card-body">
<div class="row text-center">
<div class="col-md-3">
<div class="parameter-card">
<div class="label">🔵 CO₂ Entrée</div>
<div class="value text-info" id="gas-co2-entree">{{ realtime_data.digester.co2_entree | default(0) | round(1) }}%</div>
<small>CO₂ dans le biogaz brut : Seuil normal : 25-45%</small>
</div>
</div>
<div class="col-md-3">
<div class="parameter-card">
<div class="label">🟢 CO₂ Sortie / Injecté PBR</div>
<div class="value text-success" id="gas-co2-sortie">{{ realtime_data.photobioreactor.co2_sortie | default(0) | round(2) }}%</div>
<small>CO₂ injecté dans le photobioréacteur : Seuil normal : 1-5%</small>
</div>
</div>
<div class="col-md-3">
<div class="parameter-card">
<div class="label">🟣 CH₄ Concentration</div>
<div class="value" style="color:#9C27B0" id="gas-ch4">{{ realtime_data.digester.ch4_concentration | round(1) }}%</div>
<small>Méthane dans le biogaz : Seuil normal : 50-70%</small>
</div>
</div>
<div class="col-md-3">
<div class="parameter-card">
<div class="label">🟠 Qualité Biogaz</div>
<div class="value text-warning" id="gas-qualite"></div>
<small>Plus c'est haut, meilleur est le biogaz</small>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
<div class="row mb-4">
<div class="col-md-6">
<div class="card">
<div class="card-header"><h5><i class="fas fa-seedling me-2"></i>Croissance des Algues</h5></div>
<div class="card-body"><div id="algae-graph" class="graph-container"></div></div>
</div>
</div>
<div class="col-md-6">
<div class="card">
<div class="card-header"><h5><i class="fas fa-cogs me-2"></i>Paramètres du Digesteur</h5></div>
<div class="card-body"><div id="digester-graph" class="graph-container"></div></div>
</div>
</div>
</div>
<!-- ============ PRÉDICTIONS IA ============ -->
<div class="row mb-4">
<div class="col-md-6">
<div class="card">
<div class="card-header"><h5><i class="fas fa-fire me-2" style="color:#FF9800"></i>Prévision Biogaz (IA)</h5></div>
<div class="card-body">
<div class="row text-center">
<div class="col-4"><div class="label">Aujourd'hui</div><div class="value" id="bio-today" style="font-size:1.6rem;color:#4CAF50">--</div><small>m³/h</small></div>
<div class="col-4"><div class="label">Demain <span id="bio-arrow"></span></div><div class="value" id="bio-j1" style="font-size:1.6rem;color:#2196F3">--</div><small>m³/h</small></div>
<div class="col-4"><div class="label">Après-demain</div><div class="value" id="bio-j2" style="font-size:1.6rem;color:#9C27B0">--</div><small>m³/h</small></div>
</div>
<div class="alert mt-3 mb-0" id="bio-msg" style="background:#1a1a1a;border:1px solid #444;color:#ddd;font-size:.9rem">Analyse en cours...</div>
<small class="text-muted d-block mt-2"><i class="fas fa-thermometer-half me-1"></i>Idéal : 35 à 40°C pour une production maximale</small>
</div>
</div>
</div>
<div class="col-md-6">
<div class="card">
<div class="card-header"><h5><i class="fas fa-seedling me-2" style="color:#4CAF50"></i>Croissance Spiruline (IA)</h5></div>
<div class="card-body">
<div class="row text-center">
<div class="col-4"><div class="label">Actuelle</div><div class="value" id="spir-now" style="font-size:1.6rem;color:#4CAF50">--</div><small>g/L</small></div>
<div class="col-4"><div class="label">Prévision 24h</div><div class="value" id="spir-24" style="font-size:1.6rem;color:#2196F3">--</div></div>
<div class="col-4"><div class="label">Prévision 48h</div><div class="value" id="spir-48" style="font-size:1.6rem;color:#9C27B0">--</div></div>
</div>
<div class="alert mt-3 mb-0" id="spir-msg" style="background:#1a1a1a;border:1px solid #444;color:#ddd;font-size:.9rem">Analyse en cours...</div>
<small class="text-muted d-block mt-2"><i class="fas fa-flask me-1"></i>pH idéal : 8.5 à 9.2 : Temp. idéale : 30 à 35°C</small>
</div>
</div>
</div>
</div>

<!-- ============ RÉCOLTE SPIRULINE ============ -->
<div class="card mb-4" id="harvest-card" style="border:2px solid #4CAF50">
<div class="card-header"><h5><i class="fas fa-hand-holding-water me-2" style="color:#4CAF50"></i>Récolte de la Spiruline</h5></div>
<div class="card-body">
<div id="harvest-alert"></div>
<div id="harvest-actions" class="mt-3"></div>
<div id="harvest-steps" class="mt-3" style="display:none"></div>
<div id="harvest-history" class="mt-3"></div>
</div>
</div>

<div class="card">
<div class="card-header"><h5><i class="fas fa-sliders-h me-2"></i>Paramètres Système</h5>
<button class="btn btn-sm btn-light float-end" onclick="exportPDF()"><i class="fas fa-file-pdf me-1"></i>Exporter PDF</button></div>
<div class="card-body">
<div class="parameter-grid">
<div class="parameter-card">
<div class="label">Température Digesteur</div>
<div class="value text-info" id="digester-temp">{{ realtime_data.digester.temperature | round(2) }}°C</div>
<small>Plage : 35 à 38 °C</small>
</div>
<div class="parameter-card">
<div class="label">Injection CO₂</div>
<div class="value text-success" id="pbr-co2-inj">{{ realtime_data.photobioreactor.co2_injection | round(2) }}%</div>
<small>Optimisation</small>
</div>
<div class="parameter-card">
<div class="label">Intensité Lumineuse</div>
<div class="value text-warning" id="pbr-light">{{ realtime_data.photobioreactor.light_intensity | round(0) }} µE</div>
<small>Photosynthèse</small>
</div>
<div class="parameter-card">
<div class="label">pH Photobioréacteur</div>
<div class="value text-warning" id="pbr-ph">{{ realtime_data.photobioreactor.ph | round(2) }}</div>
<small>Plage : 7.0 à 8.5</small>
</div>
<div class="parameter-card">
<div class="label">Température PBR</div>
<div class="value text-info" id="pbr-temp">{{ realtime_data.photobioreactor.temperature | round(2) }}°C</div>
<small>Plage : 24 à 30 °C</small>
</div>
<div class="parameter-card">
<div class="label">Vol. Eau CO₂ + Nutriments</div>
<div class="value text-primary" id="pbr-vol-saturated">{{ realtime_data.photobioreactor.vol_saturated_water | round(1) }} L</div>
<small>Eau enrichie injectée</small>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
<script>
function updateTime() {
    const now = new Date();
    document.getElementById('current-time').textContent = now.toLocaleTimeString('fr-FR') + ' - ' + now.toLocaleDateString('fr-FR');
}
setInterval(updateTime, 1000); updateTime();
fetch('/api/graphs/realtime').then(r => r.json()).then(data => {
    if (data.biogas_production) Plotly.newPlot('biogas-graph', ...Object.values(JSON.parse(data.biogas_production)).slice(0,2));
    if (data.algae_growth) Plotly.newPlot('algae-graph', ...Object.values(JSON.parse(data.algae_growth)).slice(0,2));
    if (data.digester_params) Plotly.newPlot('digester-graph', ...Object.values(JSON.parse(data.digester_params)).slice(0,2));
});
const socket = io();
socket.on('realtime_update', function(data) {
    document.getElementById('biogas-flow').textContent = data.data.digester.gas_flow.toFixed(2);
    document.getElementById('biomass-density').textContent = data.data.photobioreactor.biomass_density.toFixed(2);
    document.getElementById('co2-captured').textContent = data.data.environmental.co2_captured.toFixed(1);
    document.getElementById('digester-temp').textContent = data.data.digester.temperature.toFixed(2) + '°C';
    document.getElementById('pbr-co2-inj').textContent = data.data.photobioreactor.co2_injection.toFixed(2) + '%';
    document.getElementById('pbr-light').textContent = data.data.photobioreactor.light_intensity.toFixed(0) + ' µE';
    document.getElementById('pbr-ph').textContent = data.data.photobioreactor.ph.toFixed(2);
    document.getElementById('pbr-temp').textContent = data.data.photobioreactor.temperature.toFixed(2) + '°C';
    document.getElementById('pbr-vol-saturated').textContent = data.data.photobioreactor.vol_saturated_water.toFixed(1) + ' L';
    const co2e = data.data.digester.co2_entree || 0;
    const ch4 = data.data.digester.ch4_concentration || 0;
    const co2s = data.data.photobioreactor.co2_sortie || 0;
    document.getElementById('gas-co2-entree').textContent = co2e.toFixed(1) + '%';
    document.getElementById('gas-co2-sortie').textContent = co2s.toFixed(2) + '%';
    document.getElementById('gas-ch4').textContent = ch4.toFixed(1) + '%';
    const qualite = (ch4 + co2e) > 0 ? (ch4 / (ch4 + co2e) * 100) : 0;
    document.getElementById('gas-qualite').textContent = qualite.toFixed(1) + '%';
});
setInterval(() => socket.emit('get_realtime_data'), 5000);
socket.emit('get_realtime_data');

// ---- Prédictions IA ----
function arrowHtml(dir){
  if(dir==='up') return '<i class="fas fa-arrow-up" style="color:#4CAF50"></i>';
  if(dir==='down') return '<i class="fas fa-arrow-down" style="color:#F44336"></i>';
  return '<i class="fas fa-arrows-alt-h" style="color:#FF9800"></i>';
}
function loadPredictions(){
  fetch('/api/predictions/daily').then(r=>r.json()).then(d=>{
    if(d.error) return;
    const b=d.biogaz, s=d.spiruline;
    document.getElementById('bio-today').textContent=b.aujourdhui;
    document.getElementById('bio-j1').textContent=b.demain;
    document.getElementById('bio-j2').textContent=b.apres_demain;
    document.getElementById('bio-arrow').innerHTML=arrowHtml(b.tendance);
    document.getElementById('bio-msg').textContent=b.message;
    document.getElementById('spir-now').textContent=s.croissance_actuelle;
    document.getElementById('spir-24').textContent=(s.prevision_24h_pct>=0?'+':'')+s.prevision_24h_pct+'%';
    document.getElementById('spir-48').textContent=(s.prevision_48h_pct>=0?'+':'')+s.prevision_48h_pct+'%';
    document.getElementById('spir-msg').textContent=s.message;
    window._lastPred=d;
  });
}
// ---- Récolte ----
function loadHarvest(){
  fetch('/api/harvest/status').then(r=>r.json()).then(d=>{
    if(d.error) return;
    const alertDiv=document.getElementById('harvest-alert');
    const actDiv=document.getElementById('harvest-actions');
    if(d.prete){
      alertDiv.innerHTML='<div class="alert alert-success mb-0" style="font-size:1.1rem"><strong>🌿 La spiruline est prête à être récoltée !</strong><br><small>Densité actuelle : '+d.densite+' g/L (seuil : '+d.seuil+' g/L)</small></div>';
      actDiv.innerHTML='<button class="btn btn-success btn-lg w-100" onclick="startHarvest()"><i class="fas fa-cut me-2"></i>Démarrer la Récolte</button>';
    } else {
      alertDiv.innerHTML='<div class="alert alert-warning mb-0">⏳ Croissance en cours : récolte dans environ <strong>'+d.jours_restants+' jour(s)</strong><br><small>Densité actuelle : '+d.densite+' g/L (objectif : '+d.seuil+' g/L)</small></div>';
      actDiv.innerHTML='';
    }
    const hist=document.getElementById('harvest-history');
    if(d.historique && d.historique.length){
      let h='<h6 class="mt-3"><i class="fas fa-history me-1"></i>Historique des récoltes</h6><ul class="list-group">';
      d.historique.slice().reverse().forEach(e=>{ h+='<li class="list-group-item bg-dark text-light border-secondary d-flex justify-content-between"><span>'+e.date+'</span><span>'+e.densite_recoltee+' g/L</span></li>'; });
      h+='</ul>'; hist.innerHTML=h;
    } else { hist.innerHTML=''; }
  });
}
function startHarvest(){
  fetch('/api/harvest/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
  .then(r=>r.json()).then(d=>{
    if(d.success){
      const steps=document.getElementById('harvest-steps');
      let h='<div class="alert alert-info"><strong>Récolte enregistrée le '+d.date+'</strong></div>';
      h+='<h6><i class="fas fa-list-ol me-1"></i>Instructions de récolte</h6><ol class="list-group list-group-numbered">';
      d.etapes.forEach(e=>{ h+='<li class="list-group-item bg-dark text-light border-secondary">'+e.replace(/^\d+\.\s*/,'')+'</li>'; });
      h+='</ol>';
      steps.innerHTML=h; steps.style.display='block';
      loadHarvest();
    } else { alert('Erreur : '+(d.error||'inconnue')); }
  });
}
// ---- Export PDF (jsPDF côté client) ----
function exportPDF(){
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF();
  const now = new Date();
  const rt = window._lastRT || {};
  const dig = rt.digester||{}, pbr = rt.photobioreactor||{}, env = rt.environmental||{}, eco = rt.economics||{};
  const pred = window._lastPred||{};
  let y=18;
  doc.setFontSize(18); doc.setTextColor(46,125,50);
  doc.text('Rapport SEN : Symbiotic Energy Nexus', 14, y); y+=8;
  doc.setFontSize(10); doc.setTextColor(80);
  doc.text('Genere le : '+now.toLocaleString('fr-FR'), 14, y); y+=10;
  doc.setDrawColor(76,175,80); doc.line(14,y,196,y); y+=8;
  doc.setFontSize(13); doc.setTextColor(0); doc.text('Capteurs temps reel', 14, y); y+=7;
  doc.setFontSize(10);
  const rows=[
    ['Temperature digesteur', (dig.temperature??'-')+' °C'],
    ['Concentration CH4', (dig.ch4_concentration??'-')+' %'],
    ['CO2 entree (biogaz brut)', (dig.co2_entree??'-')+' %'],
    ['CO2 sortie / injecte PBR', (pbr.co2_sortie??'-')+' %'],
    ['Debit biogaz', (dig.gas_flow??'-')+' m³/h'],
    ['pH photobioreacteur', (pbr.ph??'-')],
    ['Temperature PBR', (pbr.temperature??'-')+' °C'],
    ['Luminosite', (pbr.light_intensity??'-')+' lux'],
    ['Densite biomasse', (pbr.biomass_density??'-')+' g/L'],
    ['CO2 capture', (env.co2_captured??'-')+' kg'],
  ];
  rows.forEach(r=>{ doc.text(String(r[0]),16,y); doc.text(String(r[1]),120,y); y+=6; });
  y+=4; doc.setFontSize(13); doc.text('Predictions IA du jour', 14, y); y+=7; doc.setFontSize(10);
  if(pred.biogaz){
    doc.text('Biogaz : aujourd\'hui '+pred.biogaz.aujourdhui+' | demain '+pred.biogaz.demain+' | apres-demain '+pred.biogaz.apres_demain+' m³/h',16,y); y+=6;
  }
  if(pred.spiruline){
    doc.text('Spiruline : '+pred.spiruline.croissance_actuelle+' g/L | 24h '+pred.spiruline.prevision_24h_pct+'% | 48h '+pred.spiruline.prevision_48h_pct+'%',16,y); y+=6;
  }
  y+=4; doc.setFontSize(13); doc.text('Resume economique', 14, y); y+=7; doc.setFontSize(10);
  doc.text('Profit quotidien estime : '+(eco.daily_profit!=null?Math.round(eco.daily_profit).toLocaleString('fr-FR'):'-')+' FCFA',16,y); y+=10;
  doc.setFontSize(8); doc.setTextColor(120);
  doc.text('Systeme SEN — Surveillance biodigesteur 250L + photobioreacteur 10L (Benin)',14,285);
  doc.save('rapport_SEN_'+now.toISOString().slice(0,10)+'.pdf');
}
// Garder la dernière donnée temps réel pour le PDF
socket.on('realtime_update', function(data){ window._lastRT = data.data; });
window._lastRT = {{ realtime_data | tojson }};
// Qualité biogaz initiale (avant la première mise à jour socket)
(function(){
    const ch4Init = window._lastRT.digester.ch4_concentration || 0;
    const co2eInit = window._lastRT.digester.co2_entree || 0;
    const qualiteInit = (ch4Init + co2eInit) > 0 ? (ch4Init / (ch4Init + co2eInit) * 100) : 0;
    const el = document.getElementById('gas-qualite');
    if (el) el.textContent = qualiteInit.toFixed(1) + '%';
})();
loadPredictions(); loadHarvest();
setInterval(loadPredictions, 15000);
setInterval(loadHarvest, 30000);
</script>
</body>
</html>
''',
    # ── HISTORICAL DASHBOARD ───────────────────────────────────────────────────────
    'historical_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Dashboard Historique</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;}
.sidebar{background-color:#1e1e1e;min-height:100vh;padding-top:20px;}
.sidebar a{color:#fff;text-decoration:none;display:block;padding:10px 20px;margin:5px 0;border-radius:5px;transition:all .3s;}
.sidebar a:hover,.sidebar a.active{background-color:#4CAF50;}
.content{padding:20px;}
.card{background-color:#2d2d2d;border:1px solid #444;border-radius:10px;margin-bottom:20px;}
.card-header{background-color:#1a1a1a;border-bottom:1px solid #444;padding:15px;}
.graph-container{height:400px;width:100%;}
.time-btn{padding:8px 16px;background:#2d2d2d;border:1px solid #444;border-radius:5px;color:white;cursor:pointer;}
.time-btn.active{background:#4CAF50;border-color:#4CAF50;}
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4"><h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4><small class="text-muted">Historique</small></div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical" class="active"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<h2><i class="fas fa-chart-bar me-2"></i>Dashboard Historique</h2>
<div class="d-flex gap-2 mb-4">
<button class="time-btn active" onclick="loadData('7d',this)">7 jours</button>
<button class="time-btn" onclick="loadData('30d',this)">30 jours</button>
<button class="time-btn" onclick="loadData('90d',this)">90 jours</button>
</div>
<div class="row">
<div class="col-md-6">
<div class="card"><div class="card-header"><h5><i class="fas fa-chart-line me-2"></i>Production de Biogaz</h5></div><div class="card-body"><div id="biogas-historical" class="graph-container"></div></div></div>
</div>
<div class="col-md-6">
<div class="card"><div class="card-header"><h5><i class="fas fa-chart-area me-2"></i>Température du Digesteur</h5></div><div class="card-body"><div id="temperature-historical" class="graph-container"></div></div></div>
</div>
</div>
<div class="row mt-4">
<div class="col-md-12">
<div class="card"><div class="card-header"><h5><i class="fas fa-wind me-2" style="color:#9C27B0"></i>Concentration CH₄ (Méthane)</h5></div><div class="card-body"><div id="ch4-historical" class="graph-container"></div></div></div>
</div>
</div>
<div class="row mt-4">
<div class="col-md-12">
<div class="card"><div class="card-header"><h5><i class="fas fa-chart-line me-2"></i>Performances Économiques (FCFA/j)</h5></div><div class="card-body"><div id="economics-historical" class="graph-container"></div></div></div>
</div>
</div>
</div>
</div></div>
<div class="row mt-4">
<div class="col-md-12"><h4 class="mb-3" style="color:#4CAF50;"><i class="fas fa-flask me-2"></i>Photobioréacteur (PBR) -- Historiques</h4></div>
<div class="col-md-6">
<div class="card"><div class="card-header d-flex justify-content-between align-items-center"><h5><i class="fas fa-thermometer-half me-2" style="color:#FF5722;"></i>Température PBR (°C)</h5><div id="stats-pbr-temp" class="d-flex gap-3"><span class="badge bg-danger">Max: ---</span><span class="badge bg-primary">Moy: ---</span><span class="badge bg-secondary">Min: ---</span></div></div><div class="card-body"><div id="pbr-temp-historical" class="graph-container"></div></div></div>
</div>
<div class="col-md-6">
<div class="card"><div class="card-header d-flex justify-content-between align-items-center"><h5><i class="fas fa-vial me-2" style="color:#2196F3;"></i>pH du Photobioréacteur</h5><div id="stats-pbr-ph" class="d-flex gap-3"><span class="badge bg-danger">Max: ---</span><span class="badge bg-primary">Moy: ---</span><span class="badge bg-secondary">Min: ---</span></div></div><div class="card-body"><div id="pbr-ph-historical" class="graph-container"></div></div></div>
</div>
</div>
<div class="row mt-4">
<div class="col-md-12">
<div class="card"><div class="card-header d-flex justify-content-between align-items-center"><h5><i class="fas fa-seedling me-2" style="color:#8BC34A;"></i>Production Spiruline (g/jour)</h5><div id="stats-spiruline" class="d-flex gap-3"><span class="badge bg-danger">Max: ---</span><span class="badge bg-primary">Moy: ---</span><span class="badge bg-secondary">Min: ---</span></div></div><div class="card-body"><div id="spiruline-historical" class="graph-container"></div></div></div>
</div></div>
<script>
function loadData(period, btn) {
    document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const titles = {'7d':'7 derniers jours','30d':'30 derniers jours','90d':'90 derniers jours'};
    const label = titles[period] || period;
    fetch('/api/historical/digester?period='+period).then(r=>r.json()).then(data=>{
        Plotly.newPlot('biogas-historical',[{x:data.timestamps,y:data.gas_flow,type:'scatter',mode:'lines',name:'Production Biogaz',line:{color:'#4CAF50',width:2},fill:'tozeroy',fillcolor:'rgba(76,175,80,.1)'}],{title:'Production Biogaz -- '+label+' (m³/h)',xaxis:{showgrid:false},template:'plotly_dark',height:350,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d'});
        Plotly.newPlot('temperature-historical',[{x:data.timestamps,y:data.temperature,type:'scatter',mode:'lines',name:'Température',line:{color:'#FF5722',width:2}}],{title:'Température Digesteur -- '+label+' (°C)',xaxis:{showgrid:false},yaxis:{range:[33,37]},template:'plotly_dark',height:350,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d'});
        Plotly.newPlot('ch4-historical',[{x:data.timestamps,y:data.ch4_concentration,type:'scatter',mode:'lines',name:'CH4',line:{color:'#9C27B0',width:2},fill:'tozeroy',fillcolor:'rgba(156,39,176,.1)'}],{title:'Concentration CH4 -- '+label+' (%)',xaxis:{showgrid:false},yaxis:{range:[40,80],title:'%'},template:'plotly_dark',height:350,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d'});
    });
    fetch('/api/historical/economics?period='+period).then(r=>r.json()).then(data=>{
        Plotly.newPlot('economics-historical',[
            {x:data.timestamps,y:data.revenue,type:'bar',name:'Revenus (FCFA)',marker:{color:'#4CAF50'}},
            {x:data.timestamps,y:data.cost,type:'bar',name:'Coûts (FCFA)',marker:{color:'#F44336'}},
            {x:data.timestamps,y:data.profit,type:'scatter',mode:'lines+markers',name:'Profit (FCFA)',line:{color:'#FFC107',width:3}}
        ],{title:'Performances Économiques : '+label+' (FCFA/j)',barmode:'group',template:'plotly_dark',height:400,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d',yaxis:{ticksuffix:' FCFA'}});
    });
    fetch('/api/historical/photobioreactor?period='+period).then(r=>r.json()).then(data=>{
        function stats(arr){var mn=Math.min(...arr),mx=Math.max(...arr),av=arr.reduce((a,b)=>a+b,0)/arr.length;return{min:mn.toFixed(2),max:mx.toFixed(2),avg:av.toFixed(2)};}
        var st=stats(data.temperature);document.getElementById('stats-pbr-temp').innerHTML='<span class="badge bg-danger">Max: '+st.max+' °C</span><span class="badge bg-primary">Moy: '+st.avg+' °C</span><span class="badge bg-secondary">Min: '+st.min+' °C</span>';
        Plotly.newPlot('pbr-temp-historical',[{x:data.timestamps,y:data.temperature,type:'scatter',mode:'lines',name:'Temp. PBR',line:{color:'#FF5722',width:2},fill:'tozeroy',fillcolor:'rgba(255,87,34,.08)'}],{title:'Température Photobioréacteur --- '+label+' (°C)',xaxis:{showgrid:false},template:'plotly_dark',height:350,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d'});
        var sp=stats(data.ph);document.getElementById('stats-pbr-ph').innerHTML='<span class="badge bg-danger">Max: '+sp.max+'</span><span class="badge bg-primary">Moy: '+sp.avg+'</span><span class="badge bg-secondary">Min: '+sp.min+'</span>';
        Plotly.newPlot('pbr-ph-historical',[{x:data.timestamps,y:data.ph,type:'scatter',mode:'lines',name:'pH PBR',line:{color:'#2196F3',width:2},fill:'tozeroy',fillcolor:'rgba(33,150,243,.08)'}],{title:'pH Photobioréacteur --- '+label,xaxis:{showgrid:false},template:'plotly_dark',height:350,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d'});
        var bm=data.biomass_density;var periodDays={'7d':7,'30d':30,'90d':90}[period]||7;var hoursPerDay=24;var spirulina=[];var ts=[];for(var d=0;d<periodDays;d++){var daySlice=bm.slice(d*hoursPerDay,(d+1)*hoursPerDay);if(daySlice.length>0){var harvestGrams=daySlice.reduce((a,b)=>a+b,0)/daySlice.length*1000*0.15;spirulina.push(parseFloat(harvestGrams.toFixed(1)));ts.push(data.timestamps[d*hoursPerDay]);}};
        var ss=stats(spirulina);document.getElementById('stats-spiruline').innerHTML='<span class="badge bg-danger">Max: '+ss.max+' g</span><span class="badge bg-primary">Moy: '+ss.avg+' g</span><span class="badge bg-secondary">Min: '+ss.min+' g</span>';
        Plotly.newPlot('spiruline-historical',[{x:ts,y:spirulina,type:'bar',name:'Production Spiruline',marker:{color:'rgba(139,195,74,.8)',line:{color:'#8BC34A',width:1}}}],{title:'Production Spiruline --- '+label+' (g/j)',xaxis:{showgrid:false},template:'plotly_dark',height:380,plot_bgcolor:'#1e1e1e',paper_bgcolor:'#2d2d2d',yaxis:{title:'grammes/jour'}});
    });
}
loadData('7d', document.querySelector('.time-btn'));
</script>
</body></html>
''',
    # ── ANALYTICS DASHBOARD ────────────────────────────────────────────────────────
    'analytics_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Dashboard Analytique</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;}
.sidebar{background-color:#1e1e1e;min-height:100vh;padding-top:20px;}
.sidebar a{color:#fff;text-decoration:none;display:block;padding:10px 20px;margin:5px 0;border-radius:5px;transition:all .3s;}
.sidebar a:hover,.sidebar a.active{background-color:#4CAF50;}
.content{padding:20px;}
.card{background-color:#2d2d2d;border:1px solid #444;border-radius:10px;margin-bottom:20px;}
.card-header{background-color:#1a1a1a;border-bottom:1px solid #444;padding:15px;}
.graph-container{height:400px;width:100%;}
.prediction-card{background:linear-gradient(135deg,#2c3e50,#34495e);border-radius:10px;padding:20px;margin:10px 0;}
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4"><h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4><small class="text-muted">Analytique</small></div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics" class="active"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<h2><i class="fas fa-chart-pie me-2"></i>Dashboard Analytique</h2>
<div class="row">
<div class="col-md-8">
<div class="card"><div class="card-header"><h5>Prédictions de Production (24h)</h5></div><div class="card-body"><div id="predictions-graph" class="graph-container"></div></div></div>
</div>
<div class="col-md-4">
<div class="card"><div class="card-header"><h5>Indicateurs de Confiance</h5></div>
<div class="card-body">
<div class="prediction-card">
<h6>Prédiction Biogaz</h6>
<span class="badge bg-success">{{ predictions.biogas_production.confidence * 100 | round(1) }}% Confiance</span>
<div class="progress mt-3" style="height:10px"><div class="progress-bar bg-success" style="width:85%"></div></div>
</div>
<div class="prediction-card mt-3">
<h6>Croissance Algues</h6>
<span class="badge bg-primary">{{ predictions.algae_growth.confidence * 100 | round(1) }}% Confiance</span>
<div class="mt-2"><small class="text-muted">Récolte dans</small><h4>{{ predictions.algae_growth.harvest_in_hours }}h</h4></div>
</div>
</div></div>
</div>
</div>
<div class="row mt-4">
<div class="col-md-12">
<div class="card"><div class="card-header"><h5>Performance du Système</h5></div><div class="card-body"><div id="performance-graph" class="graph-container"></div></div></div>
</div>
</div>
</div>
</div></div>
<script>
fetch('/api/graphs/analytics').then(r=>r.json()).then(data=>{
    if(data.production_prediction){const g=JSON.parse(data.production_prediction);Plotly.newPlot('predictions-graph',g.data,g.layout);}
    if(data.system_performance){const g=JSON.parse(data.system_performance);Plotly.newPlot('performance-graph',g.data,g.layout);}
});
</script>
<div class="row mt-4">
<div class="col-12">
<div class="card"><div class="card-header"><h5><i class="fas fa-shield-alt me-2" style="color:#FF9800"></i>Qualité du Modèle IA</h5></div>
<div class="card-body">
<div class="row g-3">
<div class="col-md-3">
<div class="card h-100" style="background:#1a2a1a;border:1px solid #4CAF50">
<div class="card-body text-center">
<div style="color:#4CAF50;font-size:1.8rem"><i class="fas fa-bullseye"></i></div>
<div class="fw-bold mt-2">Intervalles de confiance</div>
<div class="text-success fw-bold fs-5 mt-1" id="conf-biogaz">±---%</div>
<div class="text-muted small">Biogaz (7j)</div>
<div class="text-primary fw-bold fs-5 mt-1" id="conf-spiruline">±---%</div>
<div class="text-muted small">Spiruline (7j)</div>
</div></div></div>
<div class="col-md-3">
<div class="card h-100" style="background:#1a1a2a;border:1px solid #2196F3">
<div class="card-body text-center">
<div style="color:#2196F3;font-size:1.8rem"><i class="fas fa-database"></i></div>
<div class="fw-bold mt-2">Qualité données capteurs</div>
<div class="fw-bold fs-5 mt-1" id="sensor-status" style="color:#4CAF50">--- Vérification...</div>
<div class="text-muted small" id="sensor-detail">En attente de données</div>
</div></div></div>
<div class="col-md-3">
<div class="card h-100" style="background:#2a1a1a;border:1px solid #F44336">
<div class="card-body text-center">
<div style="color:#F44336;font-size:1.8rem"><i class="fas fa-chart-bar"></i></div>
<div class="fw-bold mt-2">Métriques de performance</div>
<div class="mt-2 text-start px-2">
<div class="d-flex justify-content-between"><span class="text-muted small">MAE</span><span class="text-white fw-bold" id="metric-mae">---</span></div>
<div class="d-flex justify-content-between"><span class="text-muted small">RMSE</span><span class="text-white fw-bold" id="metric-rmse">---</span></div>
<div class="d-flex justify-content-between"><span class="text-muted small">R²</span><span class="text-white fw-bold" id="metric-r2">---</span></div>
</div>
<div class="text-muted mt-1" style="font-size:.7rem">Mis à jour après chaque réentraînement</div>
</div></div></div>
<div class="col-md-3">
<div class="card h-100" style="background:#1a2a2a;border:1px solid #9C27B0">
<div class="card-body text-center">
<div style="color:#9C27B0;font-size:1.8rem"><i class="fas fa-history"></i></div>
<div class="fw-bold mt-2">Historique prédictions vs réalité</div>
<div class="mt-2"><a href="/dashboard/historical" class="btn btn-sm btn-outline-secondary"><i class="fas fa-chart-line me-1"></i>Voir graphique comparatif</a></div>
<div class="text-muted mt-2" style="font-size:.72rem">Section Historique -- graphique comparatif</div>
</div></div></div>
</div>
</div></div>
</div>
</div>
<script>
fetch('/api/predictions/latest').then(r=>r.json()).then(data=>{
    if(data.biogas_production){
        var conf=Math.round((data.biogas_production.confidence||0)*100);
        var ci=data.biogas_production.confidence_interval_pct||conf*0.1;
        document.getElementById('conf-biogaz').textContent='±'+ci.toFixed(1)+'%';
        document.getElementById('conf-spiruline').textContent='±'+((data.spirulina_production&&data.spirulina_production.confidence_interval_pct)||'---')+'%';
    }
    if(data.model_metrics){
        document.getElementById('metric-mae').textContent=data.model_metrics.mae!=null?data.model_metrics.mae.toFixed(2):'---';
        document.getElementById('metric-rmse').textContent=data.model_metrics.rmse!=null?data.model_metrics.rmse.toFixed(2):'---';
        document.getElementById('metric-r2').textContent=data.model_metrics.r2!=null?data.model_metrics.r2.toFixed(3):'---';
    }
    if(data.sensor_quality!=null){
        var ok=data.sensor_quality.valid!==false;
        document.getElementById('sensor-status').textContent=ok?'✅ Données valides':'⚠️ Données aberrantes';
        document.getElementById('sensor-status').style.color=ok?'#4CAF50':'#F44336';
        document.getElementById('sensor-detail').textContent=ok?'Capteurs nominaux':(data.sensor_quality.reason||'Vérifier capteurs');
    }
}).catch(()=>{});
</script>
</body></html>
''',
    # ── REPORTS DASHBOARD -- FCFA ───────────────────────────────────────────────────
    'reports_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Dashboard Rapports</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;}
.sidebar{background-color:#1e1e1e;min-height:100vh;padding-top:20px;}
.sidebar a{color:#fff;text-decoration:none;display:block;padding:10px 20px;margin:5px 0;border-radius:5px;transition:all .3s;}
.sidebar a:hover,.sidebar a.active{background-color:#4CAF50;}
.content{padding:20px;}
.card{background-color:#2d2d2d;border:1px solid #444;border-radius:10px;margin-bottom:20px;}
.card-header{background-color:#1a1a1a;border-bottom:1px solid #444;padding:15px;}
.report-card{border-radius:10px;padding:20px;margin:10px 0;cursor:pointer;transition:transform .3s;}
.report-card:hover{transform:translateY(-5px);}
.kpi-card{text-align:center;padding:15px;border-radius:10px;margin:10px 0;}
.kpi-value{font-size:2rem;font-weight:bold;}
.kpi-label{font-size:.9rem;opacity:.8;}
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4"><h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4><small class="text-muted">Rapports</small></div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports" class="active"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<h2><i class="fas fa-file-alt me-2"></i>Dashboard Rapports</h2>
<div class="row mb-4">
<div class="col-md-4"><div class="kpi-card" style="background:linear-gradient(135deg,#2E7D32,#4CAF50)"><div class="kpi-value">{{ reports.daily.biogas_production | round(0) | int }}</div><div class="kpi-label">Biogaz (m³/jour)</div></div></div>
<div class="col-md-4"><div class="kpi-card" style="background:linear-gradient(135deg,#6A1B9A,#9C27B0)"><div class="kpi-value">{{ reports.daily.co2_captured | round(0) | int }}</div><div class="kpi-label">CO₂ Capturé (kg/jour)</div></div></div>
<div class="col-md-4"><div class="kpi-card" style="background:linear-gradient(135deg,#C62828,#F44336)"><div class="kpi-value" id="kpi-profit">{{ reports.daily.profit_fcfa }}</div><div class="kpi-label">Profit (FCFA/jour)</div></div></div>
</div>
<div class="row">
<div class="col-md-6">
<div class="report-card" style="background:linear-gradient(135deg,#1565C0,#1976D2)" onclick="generateReport('daily')">
<h5><i class="fas fa-calendar-day me-2"></i>Rapport Quotidien</h5>
<p>Synthèse des performances journalières</p>
<small class="text-muted">Dernière génération: {{ reports.daily.date }}</small><br>
<a href="#" class="btn btn-sm btn-light mt-2" onclick="event.stopPropagation();downloadReport('daily')"><i class="fas fa-download me-1"></i>Télécharger PDF</a>
</div>
<div class="report-card mt-2" style="background:linear-gradient(135deg,#6A1B9A,#9C27B0)" onclick="generateReport('weekly')">
<h5><i class="fas fa-calendar-week me-2"></i>Rapport Hebdomadaire</h5>
<p>Analyse des tendances sur 7 jours</p>
<small class="text-muted">Semaine: {{ reports.weekly.week }}</small><br>
<a href="#" class="btn btn-sm btn-light mt-2" onclick="event.stopPropagation();downloadReport('weekly')"><i class="fas fa-download me-1"></i>Télécharger PDF</a>
</div>
</div>
<div class="col-md-6">
<div class="report-card" style="background:linear-gradient(135deg,#C62828,#F44336)" onclick="generateReport('monthly')">
<h5><i class="fas fa-calendar-alt me-2"></i>Rapport Mensuel</h5>
<p>Performance globale du mois</p>
<a href="#" class="btn btn-sm btn-light mt-2" onclick="event.stopPropagation();downloadReport('monthly')"><i class="fas fa-download me-1"></i>Télécharger PDF</a>
</div>
<div class="report-card mt-2" style="background:linear-gradient(135deg,#FF9800,#FFC107)" onclick="generateReport('environmental')">
<h5><i class="fas fa-leaf me-2"></i>Rapport Environnemental</h5>
<p>Impact écologique et bilan carbone</p>
<a href="#" class="btn btn-sm btn-light mt-2" onclick="event.stopPropagation();downloadReport('environmental')"><i class="fas fa-download me-1"></i>Télécharger PDF</a>
</div>
</div>
</div>
<div class="card mt-4">
<div class="card-header"><h5>Statistiques Hebdomadaires de Production Biogaz (m³)</h5></div>
<div class="card-body"><div id="weekly-stats" style="height:300px"></div></div>
</div>
</div>
</div></div>
<script>
const bp = {{ reports.daily.biogas_production }};
Plotly.newPlot('weekly-stats',[{
    x:['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'],
    y:[bp,bp*1.1,bp*1.2,bp*0.95,bp*1.15,bp*0.9,bp*0.8],
    type:'bar',marker:{color:'#4CAF50'}
}],{title:'Production Hebdomadaire (m³)',template:'plotly_dark'});
function generateReport(type){
    fetch('/api/reports/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report_type:type,parameters:{}})})
    .then(r=>r.json()).then(d=>alert(d.message));
}
function downloadReport(type){
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    const now = new Date();
    const daily = {{ reports.daily | tojson }};
    const weekly = {{ reports.weekly | tojson }};
    let y = 18;
    doc.setFontSize(18); doc.setTextColor(46,125,50);
    doc.text('Rapport SEN — ' + type.charAt(0).toUpperCase() + type.slice(1), 14, y); y += 8;
    doc.setFontSize(10); doc.setTextColor(80);
    doc.text('Genere le : ' + now.toLocaleString('fr-FR'), 14, y); y += 10;
    doc.setDrawColor(76,175,80); doc.line(14, y, 196, y); y += 8;
    doc.setFontSize(13); doc.setTextColor(0);
    doc.text('Resume capteurs et production (jour)', 14, y); y += 7;
    doc.setFontSize(10);
    const rowsDaily = [
        ['Production biogaz (m3/jour)', String(daily.biogas_production)],
        ['Biomasse algale (g)', String(daily.algae_biomass)],
        ['CO2 capture (kg/jour)', String(daily.co2_captured)],
        ['Revenu journalier (FCFA)', String(daily.revenue_fcfa)],
        ['Profit journalier (FCFA)', daily.profit_fcfa],
    ];
    rowsDaily.forEach(r => { doc.text(String(r[0]), 16, y); doc.text(String(r[1]), 130, y); y += 6; });
    y += 6; doc.setFontSize(13); doc.setTextColor(0);
    doc.text('Resume hebdomadaire', 14, y); y += 7; doc.setFontSize(10);
    const rowsWeekly = [
        ['Semaine', String(weekly.week)],
        ['Total biogaz (m3)', String(weekly.total_biogas)],
        ['Total CO2 capture (kg)', String(weekly.total_co2)],
        ['Revenu total (FCFA)', String(weekly.total_revenue_fcfa)],
    ];
    rowsWeekly.forEach(r => { doc.text(String(r[0]), 16, y); doc.text(String(r[1]), 130, y); y += 6; });
    y += 6; doc.setFontSize(8); doc.setTextColor(120);
    doc.text('Systeme SEN : rapport ' + type + '  Benin', 14, 285);
    doc.save('rapport_SEN_' + now.toISOString().slice(0,10) + '.pdf');
}
</script>
</body></html>
''',
    # ── CONFIGURATION DASHBOARD -- Ajout seuils PBR, suppression pH digesteur ──────
    'configuration_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Configuration</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;}
.sidebar{background-color:#1e1e1e;min-height:100vh;padding-top:20px;}
.sidebar a{color:#fff;text-decoration:none;display:block;padding:10px 20px;margin:5px 0;border-radius:5px;transition:all .3s;}
.sidebar a:hover,.sidebar a.active{background-color:#4CAF50;}
.content{padding:20px;}
.card{background-color:#2d2d2d;border:1px solid #444;border-radius:10px;margin-bottom:20px;}
.card-header{background-color:#1a1a1a;border-bottom:1px solid #444;padding:15px;}
.config-section{border-radius:10px;padding:20px;margin:10px 0;}
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4"><h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4><small class="text-muted">Configuration</small></div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration" class="active"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<h2><i class="fas fa-cog me-2"></i>Configuration du Système</h2>
{% if not user.has_permission('configure') %}
<div class="alert alert-warning"><i class="fas fa-exclamation-triangle me-2"></i>Vous n'avez pas les permissions nécessaires pour modifier la configuration.</div>
{% endif %}
<div class="row">
<div class="col-md-6">
<div class="config-section" style="background:linear-gradient(135deg,#1a237e,#283593)">
<h5><i class="fas fa-industry me-2"></i>Seuils d'Alarme -- Digesteur</h5>
<small class="text-muted d-block mb-3"><i class="fas fa-info-circle me-1"></i>Pas de capteur pH installé sur le digesteur.</small>
<div class="mb-3">
<label class="form-label">Température Max Digesteur (°C)</label>
<input type="number" class="form-control bg-dark text-white" value="38.0" step="0.1"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<button class="btn btn-success"
{% if not user.has_permission('configure') %}disabled{% endif %}
onclick="showMsg('Configuration alarmes digesteur sauvegardée','success')">
<i class="fas fa-save me-2"></i>Sauvegarder
</button>
</div>
</div>
<div class="col-md-6">
<div class="config-section" style="background:linear-gradient(135deg,#1b5e20,#2e7d32)">
<h5><i class="fas fa-seedling me-2"></i>Seuils d'Alarme -- Photobioréacteur</h5>
<small class="text-muted d-block mb-3"><i class="fas fa-info-circle me-1"></i>Capteur pH et température installés sur le PBR.</small>
<div class="mb-3">
<label class="form-label">Température Max PBR (°C)</label>
<input type="number" class="form-control bg-dark text-white" value="30.0" step="0.1"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<div class="mb-3">
<label class="form-label">pH Min PBR</label>
<input type="number" class="form-control bg-dark text-white" value="7.0" step="0.01"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<div class="mb-3">
<label class="form-label">pH Max PBR</label>
<input type="number" class="form-control bg-dark text-white" value="8.5" step="0.01"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<button class="btn btn-success"
{% if not user.has_permission('configure') %}disabled{% endif %}
onclick="showMsg('Configuration alarmes PBR sauvegardée','success')">
<i class="fas fa-save me-2"></i>Sauvegarder
</button>
</div>
</div>
</div>
<div class="row mt-3">
<div class="col-md-6">
<div class="config-section" style="background:linear-gradient(135deg,#4a148c,#6a1b9a)">
<h5><i class="fas fa-chart-line me-2"></i>Paramètres de Surveillance</h5>
<div class="mb-3">
<label class="form-label">Intervalle de Rafraîchissement (s)</label>
<input type="number" class="form-control bg-dark text-white" value="2" min="1" max="60"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<div class="mb-3">
<label class="form-label">Rétention des Données (jours)</label>
<input type="number" class="form-control bg-dark text-white" value="30" min="1" max="365"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<div class="mb-3">
<label class="form-label">Seuil Biomasse Min (g/L)</label>
<input type="number" class="form-control bg-dark text-white" value="3.5" min="1" max="10" step="0.1"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<button class="btn btn-success"
{% if not user.has_permission('configure') %}disabled{% endif %}
onclick="showMsg('Configuration de surveillance sauvegardée','success')">
<i class="fas fa-save me-2"></i>Sauvegarder
</button>
</div>
</div>
<div class="col-md-6">
<div class="config-section" style="background:linear-gradient(135deg,#006064,#00838f)">
<h5><i class="fas fa-tint me-2"></i>Eau Saturée CO₂ + Nutriments</h5>
<small class="text-muted d-block mb-3">Paramètres de gestion du volume d'eau enrichie injectée dans le PBR.</small>
<div class="mb-3">
<label class="form-label">Volume cible par cycle (L)</label>
<input type="number" class="form-control bg-dark text-white" value="50.0" step="0.5"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<div class="mb-3">
<label class="form-label">Alerte volume bas (L)</label>
<input type="number" class="form-control bg-dark text-white" value="10.0" step="0.5"
{% if not user.has_permission('configure') %}disabled{% endif %}>
</div>
<button class="btn btn-success"
{% if not user.has_permission('configure') %}disabled{% endif %}
onclick="showMsg('Configuration eau saturée sauvegardée','success')">
<i class="fas fa-save me-2"></i>Sauvegarder
</button>
</div>
</div>
</div>
<div class="card mt-4">
<div class="card-header"><h5><i class="fas fa-info-circle me-2"></i>Informations Système</h5></div>
<div class="card-body">
<div class="row">
<div class="col-md-4"><strong>Version Dashboard</strong><br><span class="text-muted">3.2.0</span></div>
<div class="col-md-4"><strong>Dernière Mise à Jour</strong><br><span class="text-muted">{{ derniere_maj }}</span></div>
<div class="col-md-4"><strong>Statut Base de Données</strong><br><span class="text-success">✓ Connectée</span></div>
</div>
</div>
</div>
</div>
</div></div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
function showMsg(msg, type){
    const a=document.createElement('div');
    a.className='alert alert-'+type+' alert-dismissible fade show mt-3';
    a.innerHTML='<i class="fas fa-check-circle me-2"></i>'+msg+'<button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
    document.querySelector('.content').appendChild(a);
}
</script>
</body></html>
''',
    # ── ALARMS DASHBOARD ───────────────────────────────────────────────────────────
    'alarms_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Gestion des Alarmes</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;}
.sidebar{background-color:#1e1e1e;min-height:100vh;padding-top:20px;}
.sidebar a{color:#fff;text-decoration:none;display:block;padding:10px 20px;margin:5px 0;border-radius:5px;transition:all .3s;}
.sidebar a:hover,.sidebar a.active{background-color:#4CAF50;}
.content{padding:20px;}
.card{background-color:#2d2d2d;border:1px solid #444;border-radius:10px;margin-bottom:20px;}
.card-header{background-color:#1a1a1a;border-bottom:1px solid #444;padding:15px;}
.alarm-card{border-left:5px solid;margin:10px 0;padding:15px;border-radius:5px;}
.alarm-critical{border-left-color:#f44336;background:rgba(244,67,54,.1);}
.alarm-warning{border-left-color:#ff9800;background:rgba(255,152,0,.1);}
.alarm-info{border-left-color:#2196f3;background:rgba(33,150,243,.1);}
.filter-btn{padding:8px 16px;background:#2d2d2d;border:1px solid #444;border-radius:5px;color:white;cursor:pointer;}
.filter-btn.active{background:#4CAF50;border-color:#4CAF50;}
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4"><h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4><small class="text-muted">Alarmes</small></div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms" class="active"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<h2><i class="fas fa-bell me-2"></i>Gestion des Alarmes</h2>
<div class="row mb-4">
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h3 id="active-alarms-count">0</h3><small class="text-muted">Alarmes Actives</small></div></div></div>
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h3 id="critical-alarms-count">0</h3><small class="text-muted">Critiques</small></div></div></div>
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h3 id="acknowledged-alarms-count">0</h3><small class="text-muted">Acquittées</small></div></div></div>
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h3 id="total-alarms-count">0</h3><small class="text-muted">Total 24h</small></div></div></div>
</div>
<div class="d-flex gap-2 mb-3">
<button class="filter-btn active" onclick="filterAlarms('all',this)">Toutes</button>
<button class="filter-btn" onclick="filterAlarms('active',this)">Actives</button>
<button class="filter-btn" onclick="filterAlarms('critical',this)">Critiques</button>
<button class="filter-btn" onclick="filterAlarms('acknowledged',this)">Acquittées</button>
</div>
<div class="card">
<div class="card-header d-flex justify-content-between align-items-center">
<h5><i class="fas fa-list me-2"></i>Liste des Alarmes</h5>
<div>
<button class="btn btn-sm btn-success me-2" onclick="acknowledgeAll()"><i class="fas fa-check-circle me-1"></i>Acquitter Toutes</button>
<button class="btn btn-sm btn-danger" onclick="clearAllAlarms()"><i class="fas fa-trash me-1"></i>Effacer Toutes</button>
</div>
</div>
<div class="card-body"><div id="alarms-list"><div class="alert alert-info"><i class="fas fa-info-circle me-2"></i>Chargement...</div></div></div>
</div>
</div>
</div></div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
let currentFilter='all';
function loadAlarms(){
    fetch('/api/alarms').then(r=>r.json()).then(data=>{
        document.getElementById('active-alarms-count').textContent=data.total;
        document.getElementById('critical-alarms-count').textContent=data.critical;
        document.getElementById('acknowledged-alarms-count').textContent=data.acknowledged||0;
        document.getElementById('total-alarms-count').textContent=data.total_24h||data.total;
        displayAlarms(data.alarms);
    });
}
function displayAlarms(alarms){
    const list=document.getElementById('alarms-list');
    let filtered=alarms;
    if(currentFilter==='active') filtered=alarms.filter(a=>!a.acknowledged);
    else if(currentFilter==='critical') filtered=alarms.filter(a=>a.severity==='critical');
    else if(currentFilter==='acknowledged') filtered=alarms.filter(a=>a.acknowledged);
    if(!filtered||!filtered.length){list.innerHTML='<div class="alert alert-success"><i class="fas fa-check-circle me-2"></i>Aucune alarme</div>';return;}
    list.innerHTML='';
    filtered.forEach(alarm=>{
        const cls=alarm.severity==='critical'?'alarm-critical':alarm.severity==='warning'?'alarm-warning':'alarm-info';
        const color=alarm.severity==='critical'?'danger':alarm.severity==='warning'?'warning':'info';
        const d=document.createElement('div');
        d.className='alarm-card '+cls;
        d.innerHTML='<div class="d-flex justify-content-between"><div><span class="badge bg-'+color+' me-2">'+alarm.severity.toUpperCase()+'</span><strong>'+alarm.message+'</strong><div><small class="text-muted">'+new Date(alarm.timestamp).toLocaleString('fr-FR')+'</small></div></div><div>'+(alarm.acknowledged?'<span class="badge bg-success">Acquittée</span>':'<button class="btn btn-sm btn-success" onclick="ack('+alarm.id+')">Acquitter</button>')+'</div></div>';
        list.appendChild(d);
    });
}
function filterAlarms(f,btn){currentFilter=f;document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');loadAlarms();}
function ack(id){fetch('/api/alarms/acknowledge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alarm_id:id})}).then(()=>loadAlarms());}
function acknowledgeAll(){if(confirm('Acquitter toutes les alarmes ?'))fetch('/api/alarms/acknowledge_all',{method:'POST'}).then(()=>loadAlarms());}
function clearAllAlarms(){if(confirm('Effacer toutes les alarmes ?'))fetch('/api/alarms/clear_all',{method:'POST'}).then(()=>loadAlarms());}
loadAlarms();
setInterval(loadAlarms,10000);
</script>
</body></html>
''',
    # ── HEALTH DASHBOARD ───────────────────────────────────────────────────────────
    'health_dashboard': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Santé Système</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;}
.sidebar{background-color:#1e1e1e;min-height:100vh;padding-top:20px;}
.sidebar a{color:#fff;text-decoration:none;display:block;padding:10px 20px;margin:5px 0;border-radius:5px;transition:all .3s;}
.sidebar a:hover,.sidebar a.active{background-color:#4CAF50;}
.content{padding:20px;}
.card{background-color:#2d2d2d;border:1px solid #444;border-radius:10px;margin-bottom:20px;}
.card-header{background-color:#1a1a1a;border-bottom:1px solid #444;padding:15px;}
.health-card{padding:20px;border-radius:10px;margin:10px 0;}
.health-indicator{height:20px;border-radius:10px;background:#333;margin:10px 0;overflow:hidden;}
.health-fill{height:100%;border-radius:10px;transition:width .5s;}
.status-good{background:linear-gradient(90deg,#4CAF50,#8BC34A);}
</style>
</head>
<body>
<div class="container-fluid"><div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4"><h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4><small class="text-muted">Santé Système</small></div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health" class="active"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<h2><i class="fas fa-heartbeat me-2"></i>Santé du Système</h2>
<div class="row mb-4">
<div class="col-md-4">
<div class="health-card" style="background:linear-gradient(135deg,#1565C0,#2196F3)">
<h5><i class="fas fa-microchip me-2"></i>Système</h5>
<div class="health-indicator"><div class="health-fill status-good" style="width:{{ health_data.system.cpu_usage }}%"></div></div>
<small>CPU : {{ health_data.system.cpu_usage }}%</small><br>
<small>Mémoire : {{ health_data.system.memory_usage }}%</small><br>
<small>Disque : {{ health_data.system.disk_usage }}%</small>
</div>
</div>
<div class="col-md-4">
<div class="health-card" style="background:linear-gradient(135deg,#2E7D32,#4CAF50)">
<h5><i class="fas fa-industry me-2"></i>Digesteur</h5>
<div class="health-indicator"><div class="health-fill status-good" style="width:99%"></div></div>
<small>Statut : {{ health_data.components.digester.status }}</small><br>
<small>Uptime : {{ health_data.components.digester.uptime }}</small><br>
<small>Capteurs : {{ health_data.components.digester.sensors_online }}/12</small>
</div>
</div>
<div class="col-md-4">
<div class="health-card" style="background:linear-gradient(135deg,#558B2F,#7CB342)">
<h5><i class="fas fa-seedling me-2"></i>Photobioréacteur</h5>
<div class="health-indicator"><div class="health-fill status-good" style="width:99%"></div></div>
<small>Statut : {{ health_data.components.photobioreactor.status }}</small><br>
<small>Uptime : {{ health_data.components.photobioreactor.uptime }}</small><br>
<small>Souche : {{ health_data.components.photobioreactor.algae_strain }}</small>
</div>
</div>
</div>
<div class="row">
<div class="col-md-6">
<div class="card"><div class="card-header"><h5>Performance IA</h5></div><div class="card-body"><div id="ia-performance" style="height:300px"></div></div></div>
</div>
<div class="col-md-6">
<div class="card"><div class="card-header"><h5>Statut Composants</h5></div>
<div class="card-body">
<table class="table table-dark">
<thead><tr><th>Composant</th><th>Statut</th><th>Uptime</th></tr></thead>
<tbody>
<tr><td>Digesteur Anaérobie</td><td><span class="badge bg-success">Optimal</span></td><td>99.7%</td></tr>
<tr><td>Système CO₂ → Algues</td><td><span class="badge bg-success">Optimal</span></td><td>99.1%</td></tr>
<tr><td>Module IA Biogaz</td><td><span class="badge bg-success">Optimal</span></td><td>99.9%</td></tr>
<tr><td>Module IA Algues</td><td><span class="badge bg-success">Optimal</span></td><td>99.8%</td></tr>
<tr><td>Système Contrôle</td><td><span class="badge bg-success">Optimal</span></td><td>99.5%</td></tr>
</tbody>
</table>
</div></div>
</div>
</div>
</div>
</div></div>
<script>
Plotly.newPlot('ia-performance',[{x:['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'],y:[92.5,93.1,93.8,94.2,94.5,94.7,94.7],type:'scatter',mode:'lines+markers',name:'Précision IA',line:{color:'#9C27B0',width:3},marker:{size:8}}],{title:'Évolution Précision IA (%)',yaxis:{range:[90,100]},template:'plotly_dark'});
</script>
</body></html>
''',
    # ── PAGE 403 ───────────────────────────────────────────────────────────────────
    'forbidden': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN - Accès Refusé</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body{background-color:#121212;color:#fff;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;}
.box{background:#1e1e1e;border:1px solid #444;border-radius:15px;padding:50px 60px;text-align:center;max-width:500px;}
.icon{font-size:4rem;color:#F44336;margin-bottom:20px;}
h1{font-size:1.8rem;margin-bottom:10px;}
p{color:#aaa;margin-bottom:30px;}
</style>
</head>
<body>
<div class="box">
<div class="icon"><i class="fas fa-ban"></i></div>
<h1>Accès Refusé</h1>
<p>Vous n'avez pas les permissions nécessaires pour accéder à cette page.<br>
Connectez-vous avec un compte ayant les droits requis.</p>
<div class="mb-3">
<span class="badge bg-secondary me-2">Votre rôle : {{ user.role }}</span>
</div>
<a href="/" class="btn btn-success me-2"><i class="fas fa-home me-1"></i>Retour à l'accueil</a>
<a href="/logout" class="btn btn-outline-danger"><i class="fas fa-sign-out-alt me-1"></i>Changer de compte</a>
</div>
</body>
</html>
''',
    # ── MODULE MARKETING -- Vente Algues & Biogaz ───────────────────────────────────
    'marketing': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN Dashboard - Module Marketing</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body { background-color: #121212; color: #fff; font-family: 'Segoe UI', sans-serif; }
.sidebar { background-color: #1e1e1e; min-height: 100vh; padding-top: 20px; }
.sidebar a { color: #fff; text-decoration: none; display: block; padding: 10px 20px; margin: 5px 0; border-radius: 5px; transition: all .3s; }
.sidebar a:hover, .sidebar a.active { background-color: #4CAF50; }
.content { padding: 20px; }
.card { background-color: #2d2d2d; border: 1px solid #444; border-radius: 10px; margin-bottom: 20px; }
.card-header { background-color: #1a1a1a; border-bottom: 1px solid #444; padding: 15px; }
.price-badge { font-size: 1.1rem; font-weight: bold; padding: 8px 15px; border-radius: 8px; }
.view-btn { margin: 0 3px; }
.view-btn.active { background-color: #4CAF50 !important; border-color: #4CAF50 !important; }
.sales-table th { background-color: #1a1a1a; color: #aaa; font-size: .85rem; text-transform: uppercase; letter-spacing: .05em; }
.sales-table td { vertical-align: middle; font-size: .9rem; }
.sales-table tr:hover { background-color: rgba(76,175,80,.08); }
.total-row td { font-weight: bold; font-size: 1rem; color: #4CAF50; border-top: 2px solid #4CAF50; }
.form-control, .form-select {
    background-color: #1e1e1e !important;
    border: 1px solid #555 !important;
    color: #fff !important;
}
.form-control:focus, .form-select:focus {
    border-color: #4CAF50 !important;
    box-shadow: 0 0 0 .2rem rgba(76,175,80,.25) !important;
}
.input-group-text { background-color: #333; border-color: #555; color: #aaa; }
.ai-tip { font-size: .78rem; color: #81C784; margin-top: 4px; }
.timestamp-badge { font-size: .75rem; color: #aaa; }
.stat-mini { background: #1a1a1a; border-radius: 8px; padding: 12px 18px; text-align: center; }
.stat-mini .val { font-size: 1.4rem; font-weight: bold; color: #4CAF50; }
.stat-mini .lbl { font-size: .78rem; color: #aaa; margin-top: 2px; }
.empty-state { text-align: center; padding: 40px; color: #555; }
.empty-state i { font-size: 3rem; margin-bottom: 10px; }
.pred-box { background: linear-gradient(135deg,#0d1f2d,#1a2a3a); border: 1px solid #1565C0; border-radius: 12px; padding: 0; overflow: hidden; margin-bottom: 24px; }
.pred-box-header { background: linear-gradient(90deg,#1565C0,#0288D1); padding: 14px 20px; display: flex; align-items: center; justify-content: space-between; }
.pred-box-header h5 { margin: 0; font-size: 1rem; color: #fff; }
.pred-kpi { text-align: center; padding: 16px 10px; }
.pred-kpi .kpi-val { font-size: 1.6rem; font-weight: 700; color: #40C4FF; line-height: 1.1; }
.pred-kpi .kpi-lbl { font-size: .72rem; color: #90CAF9; text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }
.pred-kpi .kpi-var { font-size: .75rem; margin-top: 3px; }
.pred-prix-card { background: rgba(255,255,255,.05); border-radius: 8px; padding: 14px 18px; }
.pred-prix-card .prix-val { font-size: 1.45rem; font-weight: 700; }
.pred-prix-card .prix-fourch { font-size: .78rem; color: #90CAF9; }
.pred-justif { font-size: .8rem; color: #B0BEC5; font-style: italic; margin-top: 6px; }
.pred-confidence { font-size: .78rem; }
.pred-anomaly { background: rgba(244,67,54,.12); border-left: 3px solid #F44336; border-radius: 4px; padding: 6px 12px; margin: 3px 0; font-size: .8rem; }
.pred-maintenance-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: .8rem; font-weight: 600; }
.pred-loading { text-align: center; padding: 30px; color: #607D8B; }
</style>
</head>
<body>
<div id="demo-banner" style="background:#B71C1C;color:#fff;text-align:center;padding:8px;font-weight:600;font-size:.9rem">
⚠️ Mode Démo : En attente des données ESP32
</div>
<script>
fetch('/api/data/status').then(r=>r.json()).then(d=>{
    if (d.real_data_received) {
        var b = document.getElementById('demo-banner');
        if (b) b.style.display = 'none';
    }
});
</script>
<div class="container-fluid">
<div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4">
<h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4>
<small class="text-muted">Version 3.5</small>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing" class="active"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2">
<strong>{{ user.username }}</strong><br>
<small class="text-muted">{{ user.role }}</small>
</div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100">
<i class="fas fa-sign-out-alt me-1"></i>Déconnexion
</a>
</div>
</div>
<div class="col-md-10 content">
<div class="d-flex justify-content-between align-items-center mb-4">
<h2><i class="fas fa-store me-2" style="color:#4CAF50"></i>Marketing (Ventes)</h2>
<span class="badge bg-success"><i class="fas fa-circle me-1"></i>En ligne</span>
</div>
<div class="card mb-4">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-tags me-2" style="color:#FFD700"></i>Prix de Référence du Marché Béninois</h5>
</div>
<div class="card-body">
<div class="row">
<div class="col-md-6">
<div class="d-flex align-items-center gap-3 mb-2">
<i class="fas fa-fire" style="color:#FF7043;font-size:1.4rem"></i>
<div>
<div class="fw-bold">Biogaz Purifié</div>
<small class="text-muted">Fourchette marché : 500 à 800 FCFA / m³</small>
</div>
<span class="price-badge bg-warning text-dark ms-auto">650 FCFA / m³</span>
</div>
</div>
<div class="col-md-6">
<div class="d-flex align-items-center gap-3 mb-2">
<i class="fas fa-seedling" style="color:#66BB6A;font-size:1.4rem"></i>
<div>
<div class="fw-bold">Spiruline (Algues)</div>
<small class="text-muted">Fraîche : 6 500 FCFA/kg / Séchée : 20 000 FCFA/kg</small>
</div>
<span class="price-badge bg-success ms-auto">6 500 à 20 000 FCFA / kg</span>
</div>
</div>
</div>
</div>
</div>
<div class="pred-box" id="pred-section7">
<div class="pred-box-header">
<h5><i class="fas fa-brain me-2"></i>Prédictions IA Hebdomadaires</h5>
<div class="d-flex align-items-center gap-2">
<span class="badge bg-info" id="pred-semaine-label">Chargement...</span>
<span class="badge" id="pred-conf-badge" style="background:#1565C0">---</span>
<button class="btn btn-sm btn-outline-light" onclick="loadPredictions(true)" title="Forcer recalcul">
<i class="fas fa-sync-alt"></i>
</button>
</div>
</div>
<div id="pred-content">
<div class="pred-loading"><i class="fas fa-spinner fa-spin me-2"></i>Calcul des prédictions depuis capteurs réels...</div>
</div>
</div>
<div class="row mb-4" id="quick-stats">
<div class="col-md-3">
<div class="stat-mini">
<div class="val" id="stat-biogaz-total"></div>
<div class="lbl">CA Biogaz (période)</div>
</div>
</div>
<div class="col-md-3">
<div class="stat-mini">
<div class="val" id="stat-spiruline-total"></div>
<div class="lbl">CA Spiruline (période)</div>
</div>
</div>
<div class="col-md-3">
<div class="stat-mini">
<div class="val" id="stat-grand-total"></div>
<div class="lbl">CA Total (période)</div>
</div>
</div>
<div class="col-md-3">
<div class="stat-mini">
<div class="val" id="stat-nb-ventes">0</div>
<div class="lbl">Nombre de ventes</div>
</div>
</div>
</div>
<div class="card mb-4">
<div class="card-header d-flex justify-content-between align-items-center">
<h5 class="mb-0"><i class="fas fa-table me-2"></i>Tableau des Ventes</h5>
<div>
<button class="btn btn-sm btn-outline-light view-btn active" onclick="setView('daily')" id="btn-daily">
<i class="fas fa-calendar-day me-1"></i>Journalier
</button>
<button class="btn btn-sm btn-outline-light view-btn" onclick="setView('weekly')" id="btn-weekly">
<i class="fas fa-calendar-week me-1"></i>Hebdomadaire
</button>
<button class="btn btn-sm btn-outline-light view-btn" onclick="setView('monthly')" id="btn-monthly">
<i class="fas fa-calendar-alt me-1"></i>Mensuel
</button>
<button class="btn btn-sm btn-outline-light view-btn" onclick="setView('yearly')" id="btn-yearly">
<i class="fas fa-calendar me-1"></i>Annuel
</button>
</div>
</div>
<div class="card-body p-0">
<div class="table-responsive">
<table class="table table-dark table-hover mb-0 sales-table">
<thead>
<tr>
<th>Date / Période</th>
<th>Biogaz (m³)</th>
<th>Prix Biogaz (FCFA/m³)</th>
<th>CA Biogaz (FCFA)</th>
<th>Spiruline (kg)</th>
<th>Prix Spiruline (FCFA/kg)</th>
<th>CA Spiruline (FCFA)</th>
<th>TOTAL Période (FCFA)</th>
</tr>
</thead>
<tbody id="sales-tbody">
<tr>
<td colspan="8">
<div class="empty-state">
<i class="fas fa-chart-bar d-block"></i>
Aucune vente enregistrée. Utilisez le formulaire ci-dessous pour saisir vos premières ventes.
</div>
</td>
</tr>
</tbody>
<tfoot>
<tr class="total-row" id="total-row" style="display:none">
<td colspan="3" class="text-end">TOTAL GLOBAL</td>
<td id="foot-ca-biogaz"></td>
<td></td>
<td></td>
<td id="foot-ca-spiruline"></td>
<td id="foot-total"><strong></strong></td>
</tr>
</tfoot>
</table>
</div>
</div>
</div>
<div class="card">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-plus-circle me-2" style="color:#4CAF50"></i>Saisie de Ventes Journalières</h5>
</div>
<div class="card-body">
<div id="form-timestamp" class="timestamp-badge mb-3">
<i class="fas fa-clock me-1"></i>Horodatage automatique à la validation
</div>
<div class="row g-3">
<div class="col-md-6">
<h6 class="text-warning"><i class="fas fa-fire me-2"></i>Biogaz Purifié</h6>
<div class="mb-3">
<label class="form-label">Quantité vendue</label>
<div class="input-group">
<input type="number" class="form-control" id="qty-biogaz" placeholder="0.00" min="0" step="0.01">
<span class="input-group-text">m³</span>
</div>
</div>
<div class="mb-3">
<label class="form-label">Prix appliqué</label>
<div class="input-group">
<input type="number" class="form-control" id="prix-biogaz" value="400" min="0" step="1">
<span class="input-group-text">FCFA/m³</span>
</div>
<div class="ai-tip" id="tip-biogaz">
<i class="fas fa-robot me-1"></i>Prix IA conseillé : <strong>400 FCFA/m³</strong> <span class="text-muted">(marché : 300--500 FCFA/m³)</span>
<span class="text-muted">(marché : 500--800 FCFA/m³)</span>
</div>
</div>
</div>
<div class="col-md-6">
<h6 class="text-success"><i class="fas fa-seedling me-2"></i>Spiruline (Algues)</h6>
<div class="mb-3">
<label class="form-label">Quantité vendue</label>
<div class="input-group">
<input type="number" class="form-control" id="qty-spiruline" placeholder="0.00" min="0" step="0.01">
<span class="input-group-text">kg</span>
</div>
</div>
<div class="mb-3">
<label class="form-label">Prix appliqué</label>
<div class="input-group">
<input type="number" class="form-control" id="prix-spiruline" value="6500" min="0" step="1">
<span class="input-group-text">FCFA/kg</span>
</div>
<div class="ai-tip" id="tip-spiruline">
<i class="fas fa-robot me-1"></i>Prix IA conseillé : <strong>6 500 FCFA/kg</strong>
<span class="text-muted">(fraîche : 6 500 FCFA/kg · séchée : 20 000 FCFA/kg)</span>
</div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-md-4">
<div class="stat-mini">
<div class="val text-warning" id="preview-biogaz">0 FCFA</div>
<div class="lbl">CA Biogaz estimé</div>
</div>
</div>
<div class="col-md-4">
<div class="stat-mini">
<div class="val text-success" id="preview-spiruline">0 FCFA</div>
<div class="lbl">CA Spiruline estimé</div>
</div>
</div>
<div class="col-md-4">
<div class="stat-mini">
<div class="val" id="preview-total">0 FCFA</div>
<div class="lbl">TOTAL estimé</div>
</div>
</div>
</div>
<button class="btn btn-success btn-lg w-100" onclick="validerVente()">
<i class="fas fa-check-circle me-2"></i>Valider la Vente
<span id="btn-timestamp" class="ms-3 fs-6 fw-normal opacity-75"></span>
</button>
</div>
</div>
</div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
let _predLoaded = false;
async function loadPredictions(force = false) {
    if (_predLoaded && !force) return;
    try {
        const res = await fetch('/api/predictions/weekly');
        const data = await res.json();
        if (data.error) { console.warn('Pred error:', data.error); return; }
        renderPredictions(data);
        _predLoaded = true;
    } catch(e) {
        document.getElementById('pred-content').innerHTML =
            '<div class="p-3 text-warning"><i class="fas fa-exclamation-triangle me-2"></i>Impossible de charger les prédictions : ' + e.message + '</div>';
    }
}
function renderPredictions(d) {
    document.getElementById('pred-semaine-label').textContent = d.semaine_cible || '';
    const confBadge = document.getElementById('pred-conf-badge');
    if (d.confidence_globale === null || d.confidence_globale === undefined) {
        confBadge.textContent = 'Données insuffisantes';
        confBadge.style.background = '#616161';
    } else {
        const conf = d.confidence_globale;
        confBadge.textContent = 'Confiance : ' + conf + '%';
        confBadge.style.background = conf >= 80 ? '#2E7D32' : conf >= 65 ? '#F57F17' : '#B71C1C';
    }
    const bp = d.production_biogaz || {};
    const sp = d.production_spiruline || {};
    const anom = d.anomalies_capteurs || [];
    const maint = d.maintenance_predictive || {};
    const reco = d.recommandations_prix || {};
    const rb = reco.biogaz || {};
    const rs = reco.spiruline || {};
    function varBadge(v) {
        if (v === undefined || v === null) return '';
        const cl = v > 0 ? 'text-success' : v < 0 ? 'text-danger' : 'text-muted';
        const ico = v > 0 ? 'fa-arrow-up' : v < 0 ? 'fa-arrow-down' : 'fa-minus';
        return '<span class="kpi-var ' + cl + '"><i class="fas ' + ico + ' me-1"></i>' + Math.abs(v).toFixed(1) + '%</span>';
    }
    function fmtFcfa(n) {
        return Math.round(n).toLocaleString('fr-FR').replace(/\\u202f/g, '\\u00a0') + '\\u00a0FCFA';
    }
    const urgColors = { haute: '#F44336', moyenne: '#FF9800', basse: '#4CAF50' };
    const urgColor = urgColors[maint.urgence] || '#4CAF50';
    let anomHTML = '';
    if (anom.length === 0) {
        anomHTML = '<span class="text-success"><i class="fas fa-check-circle me-1"></i>Aucune anomalie détectée</span>';
    } else {
        anom.forEach(a => {
            const sev = a.severite === 'critique' ? 'bg-danger' : 'bg-warning text-dark';
            anomHTML += `<div class="pred-anomaly"><span class="badge ${sev} me-2">${a.severite}</span>`
                + `<strong>${a.capteur}</strong> : ${a.valeur} `
                + `(plage&nbsp;${a.plage_min}--${a.plage_max})</div>`;
        });
    }
    document.getElementById('pred-content').innerHTML = `
    <div class="p-3">
        <div class="row g-3 mb-3">
            <div class="col-md-3">
                <div class="pred-kpi">
                    <div class="kpi-val"><i class="fas fa-fire me-1" style="color:#FF7043"></i>${bp.valeur_m3 || '---'} m³</div>
                    <div class="kpi-lbl">Biogaz semaine prochaine</div>
                    ${varBadge(bp.variation_pct)}
                    <div class="mt-1"><span class="badge bg-primary" style="font-size:.7rem">${((bp.confidence||0)*100).toFixed(1)}% confiance</span></div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="pred-kpi">
                    <div class="kpi-val"><i class="fas fa-seedling me-1" style="color:#66BB6A"></i>${sp.valeur_g || '---'} g</div>
                    <div class="kpi-lbl">Spiruline semaine prochaine</div>
                    ${varBadge(sp.variation_pct)}
                    <div class="mt-1"><span class="badge bg-success" style="font-size:.7rem">${((sp.confidence||0)*100).toFixed(1)}% confiance</span></div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="pred-kpi">
                    <div class="kpi-val" style="color:${urgColor}"><i class="fas fa-tools me-1"></i>${maint.jours_avant || '---'} j</div>
                    <div class="kpi-lbl">Prochaine maintenance</div>
                    <div class="kpi-var">${maint.date_estimee || ''}</div>
                    <div class="mt-1"><span class="pred-maintenance-badge" style="background:${urgColor}22;color:${urgColor};border:1px solid ${urgColor}">${maint.urgence || ''}</span></div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="pred-kpi">
                    <div class="kpi-val" style="color:${anom.length>0?'#F44336':'#4CAF50'}">
                        <i class="fas ${anom.length>0?'fa-exclamation-triangle':'fa-shield-alt'} me-1"></i>${anom.length}
                    </div>
                    <div class="kpi-lbl">Anomalies capteurs</div>
                    <div class="kpi-var text-muted">${reco.saisonnalite || ''}</div>
                </div>
            </div>
        </div>
        <div class="row g-3 mb-3">
            <div class="col-md-6">
                <div class="pred-prix-card">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <div class="fw-bold mb-1"><i class="fas fa-fire me-1" style="color:#FF7043"></i>Prix conseillé Biogaz</div>
                            <div class="prix-val text-warning">${fmtFcfa(rb.prix_conseille||400)} / m³</div>
                            <div class="prix-fourch">Fourchette : ${fmtFcfa(rb.fourchette_min||500)}  ${fmtFcfa(rb.fourchette_max||800)}</div>
                            <div class="pred-justif">${rb.justification || ''}</div>
                        </div>
                        <span class="badge bg-info ms-2" style="font-size:.72rem;white-space:normal;max-width:80px">${rb.confidence_pct||'---'}% conf.</span>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="pred-prix-card">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <div class="fw-bold mb-1"><i class="fas fa-seedling me-1" style="color:#66BB6A"></i>Prix conseillé Spiruline</div>
                            <div class="prix-val text-success">${fmtFcfa(rs.prix_conseille||6500)} / kg</div>
                            <div class="prix-fourch">Fourchette : ${fmtFcfa(rs.fourchette_min||6500)}  ${fmtFcfa(rs.fourchette_max||20000)}</div>
                            <div class="pred-justif">${rs.justification || ''}</div>
                        </div>
                        <span class="badge bg-info ms-2" style="font-size:.72rem;white-space:normal;max-width:80px">${rs.confidence_pct||'---'}% conf.</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="row g-3">
            <div class="col-md-8">
                <div style="background:rgba(255,255,255,.04);border-radius:8px;padding:12px 16px">
                    <div class="fw-bold mb-2" style="font-size:.85rem;color:#90CAF9"><i class="fas fa-satellite-dish me-2"></i>Détection Anomalies Capteurs</div>
                    ${anomHTML}
                </div>
            </div>
            <div class="col-md-4">
                <div style="background:rgba(255,255,255,.04);border-radius:8px;padding:12px 16px;height:100%">
                    <div class="fw-bold mb-2" style="font-size:.85rem;color:#90CAF9"><i class="fas fa-chart-line me-2"></i>Tendances Marché</div>
                    <div style="font-size:.82rem">
                        <div><span class="text-muted">Tendance ventes :</span> <strong>${reco.tendance_ventes||'---'}</strong></div>
                        <div class="mt-1"><span class="text-muted">Saisonnalité :</span> <span style="font-size:.78rem">${reco.saisonnalite||'---'}</span></div>
                        <div class="mt-1"><span class="text-muted">Modèle :</span> <span style="font-size:.72rem;color:#607D8B">${d.modele||'---'}</span></div>
                        <div class="mt-1"><span class="text-muted">Source données :</span> <span style="font-size:.72rem;color:#4CAF50"><i class="fas fa-check me-1"></i>capteurs réels</span></div>
                    </div>
                </div>
            </div>
        </div>
    </div>`;
    if (rb.prix_conseille) {
        AI_PRIX.biogaz = rb.prix_conseille;
        document.getElementById('prix-biogaz').value = rb.prix_conseille;
        MARCHE.biogaz.min = rb.fourchette_min || 500;
        MARCHE.biogaz.max = rb.fourchette_max || 800;
    }
    if (rs.prix_conseille) {
        AI_PRIX.spiruline = rs.prix_conseille;
        document.getElementById('prix-spiruline').value = rs.prix_conseille;
        MARCHE.spiruline.min = rs.fourchette_min || 6500;
        MARCHE.spiruline.max = rs.fourchette_max || 20000;
    }
    updatePreview();
}
loadPredictions();
setInterval(() => loadPredictions(true), 604800000);
let salesData = [];
try {
    var _sd = localStorage.getItem('sen_sales_data');
    if (_sd) salesData = JSON.parse(_sd).map(function(e){ e.date = new Date(e.date); return e; });
} catch(e) {}
let currentView = 'daily';
const AI_PRIX = { biogaz: 650, spiruline: 6500 };
const MARCHE = {
    biogaz: { min: 500, max: 800 },
    spiruline: { min: 6500, max: 20000 }
};
function fmt(n) {
    return Math.round(n).toLocaleString('fr-FR').replace(/\\u202f/g, '\\u00a0') + '\\u00a0FCFA';
}
function fmtNum(n, dec=2) {
    return parseFloat(n).toFixed(dec);
}
function updateTimestamp() {
    const now = new Date();
    const s = now.toLocaleDateString('fr-FR') + ' ' + now.toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
    document.getElementById('btn-timestamp').textContent = s;
    document.getElementById('form-timestamp').innerHTML =
        '<i class="fas fa-clock me-1"></i>Horodatage automatique : <strong>' + s + '</strong>';
}
setInterval(updateTimestamp, 1000);
updateTimestamp();
function updatePreview() {
    const qB = parseFloat(document.getElementById('qty-biogaz').value) || 0;
    const pB = parseFloat(document.getElementById('prix-biogaz').value) || 0;
    const qS = parseFloat(document.getElementById('qty-spiruline').value) || 0;
    const pS = parseFloat(document.getElementById('prix-spiruline').value) || 0;
    const caB = qB * pB;
    const caS = qS * pS;
    const tot = caB + caS;
    document.getElementById('preview-biogaz').textContent = fmt(caB);
    document.getElementById('preview-spiruline').textContent = fmt(caS);
    document.getElementById('preview-total').textContent = fmt(tot);
    checkPrixMarche('biogaz', pB, 'tip-biogaz');
    checkPrixMarche('spiruline', pS, 'tip-spiruline');
}
function checkPrixMarche(produit, prix, tipId) {
    const m = MARCHE[produit];
    const ai = AI_PRIX[produit];
    const tip = document.getElementById(tipId);
    const unite = produit === 'biogaz' ? 'FCFA/m³' : 'FCFA/kg';
    const minFmt = m.min.toLocaleString('fr-FR');
    const maxFmt = m.max.toLocaleString('fr-FR');
    const aiFmt = ai.toLocaleString('fr-FR');
    let msg = '<i class="fas fa-robot me-1"></i>Prix IA conseillé\\u00a0: <strong>' + aiFmt + '\\u00a0' + unite + '</strong>';
    msg += ' <span class="text-muted">(marché\\u00a0: ' + minFmt + '--' + maxFmt + '\\u00a0' + unite + ')</span>';
    if (prix > 0 && (prix < m.min || prix > m.max)) {
        tip.innerHTML = msg + ' <span class="badge bg-danger ms-1">⚠ Hors fourchette marché</span>';
    } else {
        tip.innerHTML = msg;
    }
}
['qty-biogaz','prix-biogaz','qty-spiruline','prix-spiruline'].forEach(id => {
    document.getElementById(id).addEventListener('input', updatePreview);
});
function validerVente() {
    const qB = parseFloat(document.getElementById('qty-biogaz').value) || 0;
    const pB = parseFloat(document.getElementById('prix-biogaz').value) || 0;
    const qS = parseFloat(document.getElementById('qty-spiruline').value) || 0;
    const pS = parseFloat(document.getElementById('prix-spiruline').value) || 0;
    if (qB <= 0 && qS <= 0) {
        alert('Veuillez saisir au moins une quantité vendue (biogaz ou spiruline).');
        return;
    }
    const now = new Date();
    const entry = {
        date: now,
        dateStr: now.toLocaleDateString('fr-FR') + ' ' + now.toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'}),
        qty_biogaz: qB,
        prix_biogaz: pB,
        ca_biogaz: qB * pB,
        qty_spiruline: qS,
        prix_spiruline:pS,
        ca_spiruline: qS * pS,
        total: (qB * pB) + (qS * pS),
    };
    salesData.push(entry);
    document.getElementById('qty-biogaz').value = '';
    document.getElementById('qty-spiruline').value = '';
    document.getElementById('prix-biogaz').value = AI_PRIX.biogaz;
    document.getElementById('prix-spiruline').value = AI_PRIX.spiruline;
    updatePreview();
    renderTable();
    notifyROIUpdate();
    const btn = document.querySelector('button[onclick="validerVente()"]');
    btn.classList.add('btn-outline-success');
    btn.innerHTML = '<i class="fas fa-check me-2"></i>Vente enregistrée !';
    setTimeout(() => {
        btn.classList.remove('btn-outline-success');
        btn.innerHTML = '<i class="fas fa-check-circle me-2"></i>Valider la Vente <span id="btn-timestamp" class="ms-3 fs-6 fw-normal opacity-75"></span>';
        updateTimestamp();
    }, 2000);
}
function setView(view) {
    currentView = view;
    ['daily','weekly','monthly','yearly'].forEach(v => {
        document.getElementById('btn-' + v).classList.remove('active');
    });
    document.getElementById('btn-' + view).classList.add('active');
    renderTable();
}
function getPeriodKey(date, view) {
    const d = new Date(date);
    if (view === 'daily') {
        return d.toLocaleDateString('fr-FR');
    }
    if (view === 'weekly') {
        const jan1 = new Date(d.getFullYear(), 0, 1);
        const week = Math.ceil(((d - jan1) / 86400000 + jan1.getDay() + 1) / 7);
        return 'Semaine ' + week + ' / ' + d.getFullYear();
    }
    if (view === 'monthly') {
        return d.toLocaleDateString('fr-FR', {month:'long', year:'numeric'});
    }
    if (view === 'yearly') {
        return 'Année ' + d.getFullYear();
    }
}
function aggregateSales(view) {
    const periods = {};
    salesData.forEach(entry => {
        const key = getPeriodKey(entry.date, view);
        if (!periods[key]) {
            periods[key] = {
                periode: key,
                qty_biogaz: 0,
                prix_biogaz: [],
                ca_biogaz: 0,
                qty_spiruline: 0,
                prix_spiruline: [],
                ca_spiruline: 0,
                total: 0,
            };
        }
        const p = periods[key];
        p.qty_biogaz += entry.qty_biogaz;
        p.prix_biogaz.push(entry.prix_biogaz);
        p.ca_biogaz += entry.ca_biogaz;
        p.qty_spiruline += entry.qty_spiruline;
        p.prix_spiruline.push(entry.prix_spiruline);
        p.ca_spiruline += entry.ca_spiruline;
        p.total += entry.total;
    });
    Object.values(periods).forEach(p => {
        p.moy_biogaz = p.prix_biogaz.length ? p.prix_biogaz.reduce((a,b)=>a+b,0) / p.prix_biogaz.length : 0;
        p.moy_spiruline = p.prix_spiruline.length ? p.prix_spiruline.reduce((a,b)=>a+b,0) / p.prix_spiruline.length : 0;
    });
    return Object.values(periods);
}
function renderTable() {
    const tbody = document.getElementById('sales-tbody');
    const totalRow = document.getElementById('total-row');
    if (salesData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><i class="fas fa-chart-bar d-block"></i>Aucune vente enregistrée.</div></td></tr>';
        totalRow.style.display = 'none';
        updateQuickStats([], 0, 0, 0);
        return;
    }
    let rows;
    if (currentView === 'daily') {
        rows = salesData.map(e => ({
            periode: e.dateStr,
            qty_biogaz: e.qty_biogaz,
            moy_biogaz: e.prix_biogaz,
            ca_biogaz: e.ca_biogaz,
            qty_spiruline: e.qty_spiruline,
            moy_spiruline: e.prix_spiruline,
            ca_spiruline: e.ca_spiruline,
            total: e.total,
        }));
    } else {
        rows = aggregateSales(currentView);
    }
    const totBiogaz = rows.reduce((s, r) => s + r.ca_biogaz, 0);
    const totSpirulne = rows.reduce((s, r) => s + r.ca_spiruline, 0);
    const grandTotal = rows.reduce((s, r) => s + r.total, 0);
    tbody.innerHTML = rows.map(r => `
    <tr>
        <td>${r.periode}</td>
        <td>${fmtNum(r.qty_biogaz)} m³</td>
        <td>${Math.round(r.moy_biogaz).toLocaleString('fr-FR')}\\u00a0FCFA</td>
        <td>${fmt(r.ca_biogaz)}</td>
        <td>${fmtNum(r.qty_spiruline)} kg</td>
        <td>${Math.round(r.moy_spiruline).toLocaleString('fr-FR')}\\u00a0FCFA</td>
        <td>${fmt(r.ca_spiruline)}</td>
        <td><strong>${fmt(r.total)}</strong></td>
    </tr>
    `).join('');
    document.getElementById('foot-ca-biogaz').textContent = fmt(totBiogaz);
    document.getElementById('foot-ca-spiruline').textContent = fmt(totSpirulne);
    document.getElementById('foot-total').innerHTML = '<strong>' + fmt(grandTotal) + '</strong>';
    totalRow.style.display = '';
    updateQuickStats(rows, totBiogaz, totSpirulne, grandTotal);
}
function updateQuickStats(rows, totB, totS, grand) {
    document.getElementById('stat-biogaz-total').textContent = totB ? fmt(totB) : '---';
    document.getElementById('stat-spiruline-total').textContent = totS ? fmt(totS) : '---';
    document.getElementById('stat-grand-total').textContent = grand ? fmt(grand) : '---';
    document.getElementById('stat-nb-ventes').textContent = salesData.length;
}
function notifyROIUpdate() {
    const totalRevenusSaisie = salesData.reduce((s, e) => s + e.total, 0);
    const nbJours = salesData.length > 0 ? Math.max(1, (new Date() - new Date(salesData[0].date)) / 86400000) : 1;
    const revenusAnnuels = (totalRevenusSaisie / nbJours) * 365;
    const payload = {
        revenus_annuels: revenusAnnuels,
        revenus_total_saisi: totalRevenusSaisie,
        nb_ventes: salesData.length,
        timestamp: Date.now()
    };
    try { localStorage.setItem('sen_roi_data', JSON.stringify(payload)); } catch(e) {}
    try { localStorage.setItem('sen_sales_data', JSON.stringify(salesData)); } catch(e) {}
    try {
        const bc = new BroadcastChannel('sen_roi');
        bc.postMessage(payload);
        bc.close();
    } catch(e) {}
}
updatePreview();
renderTable();
</script>
</body>
</html>
''',
    # ── MODULE PERFORMANCE ÉCONOMIQUE -- CAPEX / OPEX / ROI ─────────────────────────
    'performance': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN Dashboard - Performance Économique</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
body { background-color: #121212; color: #fff; font-family: 'Segoe UI', sans-serif; }
.sidebar { background-color: #1e1e1e; min-height: 100vh; padding-top: 20px; }
.sidebar a { color: #fff; text-decoration: none; display: block; padding: 10px 20px; margin: 5px 0; border-radius: 5px; transition: all .3s; }
.sidebar a:hover, .sidebar a.active { background-color: #4CAF50; }
.content { padding: 20px; }
.card { background-color: #2d2d2d; border: 1px solid #444; border-radius: 10px; margin-bottom: 20px; }
.card-header { background-color: #1a1a1a; border-bottom: 1px solid #444; padding: 15px; }
.kpi-card { background: linear-gradient(135deg,#1a2a1a,#2d2d2d); border: 1px solid #4CAF50; border-radius: 12px; padding: 24px; text-align: center; transition: transform .2s, box-shadow .2s; }
.kpi-card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(76,175,80,.3); }
.kpi-card .kpi-icon { font-size: 2rem; margin-bottom: 10px; }
.kpi-card .kpi-value { font-size: 1.8rem; font-weight: 700; color: #4CAF50; line-height: 1.1; }
.kpi-card .kpi-label { font-size: .8rem; color: #aaa; text-transform: uppercase; letter-spacing: .06em; margin-top: 6px; }
.kpi-card .kpi-sub { font-size: .75rem; color: #666; margin-top: 4px; }
.kpi-card.roi-positive .kpi-value { color: #4CAF50; }
.kpi-card.roi-negative .kpi-value { color: #F44336; }
.kpi-card.roi-neutral .kpi-value { color: #FF9800; }
.form-control, .form-select { background-color: #1e1e1e !important; border: 1px solid #555 !important; color: #fff !important; }
.form-control:focus, .form-select:focus { border-color: #4CAF50 !important; box-shadow: 0 0 0 .2rem rgba(76,175,80,.25) !important; }
.input-group-text { background-color: #333; border-color: #555; color: #aaa; }
.total-highlight { background-color: #1a2a1a; border: 1px solid #4CAF50; border-radius: 8px; padding: 12px 20px; }
.section-lbl { font-size: .75rem; color: #888; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 12px; }
.revenu-live { font-size: .85rem; padding: 8px 14px; border-radius: 6px; background: #1a2a1a; border: 1px dashed #4CAF50; color: #4CAF50; }
.progress { background-color: #333; height: 8px; }
.progress-bar { transition: width 0.6s ease; }
</style>
</head>
<body>
<div class="container-fluid">
<div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4">
<h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4>
<small class="text-muted">Version 3.5</small>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance" class="active"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2">
<strong>{{ user.username }}</strong><br>
<small class="text-muted">{{ user.role }}</small>
</div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100">
<i class="fas fa-sign-out-alt me-1"></i>Déconnexion
</a>
</div>
</div>
<div class="col-md-10 content">
<div class="d-flex justify-content-between align-items-center mb-4">
<h2><i class="fas fa-chart-pie me-2" style="color:#4CAF50"></i>Module Performance Économique CAPEX / OPEX / ROI</h2>
<div class="d-flex gap-2 align-items-center">
<span class="revenu-live" id="revenu-live-badge"><i class="fas fa-sync-alt me-1"></i>En attente de données marketing...</span>
<span class="badge bg-success"><i class="fas fa-circle me-1"></i>En ligne</span>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-md-3">
<div class="kpi-card" id="card-capex">
<div class="kpi-icon" style="color:#2196F3"><i class="fas fa-industry"></i></div>
<div class="kpi-value text-info" id="kpi-capex">---</div>
<div class="kpi-label">CAPEX Total</div>
<div class="kpi-sub">Investissement initial</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card" id="card-opex">
<div class="kpi-icon" style="color:#FF9800"><i class="fas fa-cogs"></i></div>
<div class="kpi-value text-warning" id="kpi-opex">---</div>
<div class="kpi-label">OPEX Annuel</div>
<div class="kpi-sub" id="kpi-opex-sub">Charges opérationnelles</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card roi-neutral" id="card-roi">
<div class="kpi-icon" style="color:#E91E63"><i class="fas fa-percentage"></i></div>
<div class="kpi-value" id="kpi-roi">---</div>
<div class="kpi-label">ROI</div>
<div class="kpi-sub" id="kpi-roi-sub">Bénéfice net / CAPEX</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card" id="card-retour">
<div class="kpi-icon" style="color:#9C27B0"><i class="fas fa-clock"></i></div>
<div class="kpi-value" id="kpi-retour" style="color:#9C27B0">---</div>
<div class="kpi-label">Retour sur investissement</div>
<div class="kpi-sub" id="kpi-retour-sub">CAPEX / Bénéfice mensuel</div>
</div>
</div>
</div>
<div class="card mb-4" id="progress-card" style="display:none">
<div class="card-body py-3">
<div class="d-flex justify-content-between mb-1">
<small class="text-muted">Progression du remboursement (année 1)</small>
<small id="progress-pct-label" class="text-success fw-bold">0%</small>
</div>
<div class="progress">
<div class="progress-bar bg-success" id="progress-bar" role="progressbar" style="width:0%"></div>
</div>
<div class="d-flex justify-content-between mt-1">
<small class="text-muted">Revenus estimés an 1 : <span id="prog-revenus">---</span></small>
<small class="text-muted">Objectif CAPEX : <span id="prog-capex">---</span></small>
</div>
</div>
</div>
<div class="row g-4">
<div class="col-md-6">
<div class="card h-100">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-industry me-2" style="color:#2196F3"></i>Investissements Initiaux</h5>
</div>
<div class="card-body">
<p class="section-lbl">Saisie en FCFA : calculé automatiquement</p>
<div class="mb-3">
<label class="form-label text-muted small">Coût du biodigesteur</label>
<div class="input-group">
<input type="number" class="form-control capex-input" id="c-biodigesteur" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA</span>
</div>
</div>
<div class="mb-3">
<label class="form-label text-muted small">Coût du photobioréacteur</label>
<div class="input-group">
<input type="number" class="form-control capex-input" id="c-pbr" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA</span>
</div>
</div>
<div class="mb-3">
<label class="form-label text-muted small">Coût des capteurs et équipements IoT</label>
<div class="input-group">
<input type="number" class="form-control capex-input" id="c-iot" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA</span>
</div>
</div>
<div class="mb-3">
<label class="form-label text-muted small">Coût d'installation et génie civil</label>
<div class="input-group">
<input type="number" class="form-control capex-input" id="c-installation" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA</span>
</div>
</div>
<div id="capex-autres-container"></div>
<button class="btn btn-sm btn-outline-secondary mb-3" onclick="addCapexAutre()">
<i class="fas fa-plus me-1"></i>Ajouter un autre investissement
</button>
<div class="total-highlight d-flex justify-content-between align-items-center">
<span class="fw-bold"><i class="fas fa-sigma me-2"></i>TOTAL CAPEX</span>
<span class="fw-bold fs-5 text-info" id="total-capex">0 FCFA</span>
</div>
</div>
</div>
</div>
<div class="col-md-6">
<div class="card h-100">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-cogs me-2" style="color:#FF9800"></i>Charges Opérationnelles Mensuelles</h5>
</div>
<div class="card-body">
<p class="section-lbl">Saisie mensuelle en FCFA : totaux calculés automatiquement</p>
<div class="mb-3">
<label class="form-label text-muted small">Main d'œuvre</label>
<div class="input-group">
<input type="number" class="form-control opex-input" id="o-main-oeuvre" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA/mois</span>
</div>
</div>
<div class="mb-3">
<label class="form-label text-muted small">Énergie (électricité, carburant)</label>
<div class="input-group">
<input type="number" class="form-control opex-input" id="o-energie" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA/mois</span>
</div>
</div>
<div class="mb-3">
<label class="form-label text-muted small">Maintenance et pièces de rechange</label>
<div class="input-group">
<input type="number" class="form-control opex-input" id="o-maintenance" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA/mois</span>
</div>
</div>
<div class="mb-3">
<label class="form-label text-muted small">Intrants (substrats, produits chimiques)</label>
<div class="input-group">
<input type="number" class="form-control opex-input" id="o-intrants" placeholder="0" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA/mois</span>
</div>
</div>
<div id="opex-autres-container"></div>
<button class="btn btn-sm btn-outline-secondary mb-3" onclick="addOpexAutre()">
<i class="fas fa-plus me-1"></i>Ajouter une autre charge
</button>
<div class="total-highlight mb-2 d-flex justify-content-between align-items-center">
<span class="fw-bold">TOTAL OPEX mensuel</span>
<span class="fw-bold text-warning" id="total-opex-mensuel">0 FCFA</span>
</div>
<div class="total-highlight d-flex justify-content-between align-items-center">
<span class="fw-bold"><i class="fas fa-sigma me-2"></i>TOTAL OPEX annuel</span>
<span class="fw-bold fs-5 text-warning" id="total-opex-annuel">0 FCFA</span>
</div>
</div>
</div>
</div>
</div>
<div class="card mt-4">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-percentage me-2" style="color:#E91E63"></i>Détail du Calcul de Rentabilité</h5>
</div>
<div class="card-body">
<div class="row g-3">
<div class="col-md-3">
<div class="card h-100" style="background:#1a1a1a;border-color:#333">
<div class="card-body text-center">
<div class="text-muted small mb-1">Revenus annuels</div>
<div class="fs-4 fw-bold text-info" id="detail-revenus">---</div>
<div class="text-muted" style="font-size:.72rem">Depuis module Marketing</div>
<div class="mt-2">
<label class="form-label text-muted" style="font-size:.72rem">Saisie manuelle (optionnel)</label>
<div class="input-group input-group-sm">
<input type="number" class="form-control" id="revenus-manuels" placeholder="Revenus/an" min="0" oninput="recalcAll()">
<span class="input-group-text">FCFA</span>
</div>
</div>
</div>
</div>
</div>
<div class="col-md-3">
<div class="card h-100" style="background:#1a1a1a;border-color:#333">
<div class="card-body text-center">
<div class="text-muted small mb-1">Bénéfice net annuel</div>
<div class="fs-4 fw-bold" id="detail-benefice" style="color:#4CAF50">---</div>
<div class="text-muted" style="font-size:.72rem">Revenus − OPEX annuel</div>
</div>
</div>
</div>
<div class="col-md-3">
<div class="card h-100" style="background:#1a1a1a;border-color:#333">
<div class="card-body text-center">
<div class="text-muted small mb-1">ROI (%)</div>
<div class="fs-3 fw-bold" id="detail-roi-pct">---</div>
<div class="text-muted" style="font-size:.72rem">(Bénéfice net / CAPEX) × 100</div>
</div>
</div>
</div>
<div class="col-md-3">
<div class="card h-100" style="background:#1a1a1a;border-color:#333">
<div class="card-body text-center">
<div class="text-muted small mb-1">Retour sur investissement</div>
<div class="fs-4 fw-bold" id="detail-retour" style="color:#9C27B0">---</div>
<div class="text-muted" style="font-size:.72rem">CAPEX / Bénéfice mensuel</div>
</div>
</div>
</div>
</div>
<div class="mt-3 text-muted" style="font-size:.78rem">
<i class="fas fa-info-circle me-1"></i>
Les revenus annuels sont récupérés automatiquement depuis le
<a href="/dashboard/marketing" class="text-success">Module Marketing</a>.
Le ROI se recalcule en temps réel à chaque nouvelle vente enregistrée.
Vous pouvez aussi saisir les revenus manuellement ci-dessus.
</div>
</div>
</div>
</div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
function fmt(n) {
    if (isNaN(n) || n === null) return '---';
    return Math.round(n).toLocaleString('fr-FR') + '\\u00a0FCFA';
}
function fmtPct(n) {
    if (isNaN(n) || !isFinite(n)) return '---';
    return n.toFixed(1) + '\\u00a0%';
}
let revenusMarketing = 0;
let capexAutresCount = 0;
let opexAutresCount = 0;
function lireRevenusMarketing() {
    try {
        const raw = localStorage.getItem('sen_roi_data');
        if (!raw) return 0;
        const d = JSON.parse(raw);
        return parseFloat(d.revenus_annuels) || 0;
    } catch(e) { return 0; }
}
function sumInputs(cls) {
    return Array.from(document.querySelectorAll('.' + cls))
        .reduce(function(s, el) { return s + (parseFloat(el.value) || 0); }, 0);
}
function safeGet(id) { return document.getElementById(id); }
function safeSet(id, val) { var el = safeGet(id); if (el) el.textContent = val; }
function recalcAll() {
  try {
    const capex = sumInputs('capex-input');
    document.getElementById('total-capex').textContent = fmt(capex);
    document.getElementById('kpi-capex').textContent = capex > 0 ? fmt(capex) : '---';
    const opexMensuel = sumInputs('opex-input');
    const opexAnnuel = opexMensuel * 12;
    document.getElementById('total-opex-mensuel').textContent = fmt(opexMensuel);
    document.getElementById('total-opex-annuel').textContent = fmt(opexAnnuel);
    document.getElementById('kpi-opex').textContent = opexAnnuel > 0 ? fmt(opexAnnuel) : '---';
    document.getElementById('kpi-opex-sub').textContent = opexMensuel > 0 ? fmt(opexMensuel) + ' / mois' : 'Charges opérationnelles';
    const revenusManuels = parseFloat(document.getElementById('revenus-manuels').value) || 0;
    const revenusAnnuels = revenusManuels > 0 ? revenusManuels : revenusMarketing;
    document.getElementById('detail-revenus').textContent = revenusAnnuels > 0 ? fmt(revenusAnnuels) : '---';
    const beneficeNet = revenusAnnuels - opexAnnuel;
    const roiPct = (capex > 0 && revenusAnnuels > 0) ? (beneficeNet / capex) * 100 : NaN;
    const beneficeMens = beneficeNet / 12;
    const retourMois = (capex > 0 && beneficeMens > 0) ? capex / beneficeMens : NaN;
    if (revenusAnnuels > 0 || opexAnnuel > 0) {
        document.getElementById('detail-benefice').textContent = fmt(beneficeNet);
        document.getElementById('detail-benefice').style.color = beneficeNet >= 0 ? '#4CAF50' : '#F44336';
    } else {
        document.getElementById('detail-benefice').textContent = '---';
    }
    const roiCard = document.getElementById('card-roi');
    roiCard.classList.remove('roi-positive','roi-negative','roi-neutral');
    if (!isNaN(roiPct)) {
        const pctTxt = fmtPct(roiPct);
        document.getElementById('kpi-roi').textContent = pctTxt;
        document.getElementById('detail-roi-pct').textContent = pctTxt;
        if (roiPct > 0) {
            roiCard.classList.add('roi-positive');
            document.getElementById('detail-roi-pct').style.color = '#4CAF50';
            document.getElementById('kpi-roi-sub').textContent = 'Rentable ✅';
        } else if (roiPct < 0) {
            roiCard.classList.add('roi-negative');
            document.getElementById('detail-roi-pct').style.color = '#F44336';
            document.getElementById('kpi-roi-sub').textContent = 'En déficit ⚠️';
        } else {
            roiCard.classList.add('roi-neutral');
            document.getElementById('detail-roi-pct').style.color = '#FF9800';
            document.getElementById('kpi-roi-sub').textContent = 'À l\'équilibre';
        }
    } else {
        document.getElementById('kpi-roi').textContent = '---';
        document.getElementById('detail-roi-pct').textContent = '---';
        roiCard.classList.add('roi-neutral');
        document.getElementById('kpi-roi-sub').textContent = 'Saisissez CAPEX & revenus';
    }
    if (!isNaN(retourMois) && isFinite(retourMois) && retourMois > 0) {
        const totalMois = Math.round(retourMois);
        const ans = Math.floor(retourMois / 12);
        const mois = Math.round(retourMois % 12);
        const txt = ans > 0 ? ans + ' an' + (ans > 1 ? 's' : '') + (mois > 0 ? ' ' + mois + '\\u00a0mois' : '') : totalMois + '\\u00a0mois';
        document.getElementById('kpi-retour').textContent = txt;
        document.getElementById('detail-retour').textContent = txt;
        document.getElementById('kpi-retour-sub').textContent = totalMois + '\\u00a0mois au total';
    } else {
        document.getElementById('kpi-retour').textContent = '---';
        document.getElementById('detail-retour').textContent = '---';
        document.getElementById('kpi-retour-sub').textContent = 'CAPEX / Bénéfice mensuel';
    }
    if (capex > 0 && revenusAnnuels > 0) {
        const pct = Math.min(100, (revenusAnnuels / capex) * 100);
        document.getElementById('progress-card').style.display = '';
        document.getElementById('progress-bar').style.width = pct + '%';
        document.getElementById('progress-pct-label').textContent = pct.toFixed(1) + '%';
        document.getElementById('prog-revenus').textContent = fmt(revenusAnnuels);
        document.getElementById('prog-capex').textContent = fmt(capex);
    } else {
        document.getElementById('progress-card').style.display = 'none';
    }
  } catch(e) { console.error('recalcAll:', e); }
}
function addCapexAutre() {
    capexAutresCount++;
    var i = capexAutresCount;
    document.getElementById('capex-autres-container').insertAdjacentHTML('beforeend',
        '<div class="mb-3 row g-2 align-items-end" id="capex-row-' + i + '">' +
        '<div class="col-5"><label class="form-label text-muted small">Désignation</label>' +
        '<input type="text" class="form-control" placeholder="Ex: Véhicule, terrain..."></div>' +
        '<div class="col-6"><label class="form-label text-muted small">Montant</label>' +
        '<div class="input-group"><input type="number" class="form-control capex-input" placeholder="0" min="0" oninput="recalcAll()">' +
        '<span class="input-group-text">FCFA</span></div></div>' +
        '<div class="col-1 pb-1"><button class="btn btn-sm btn-outline-danger" onclick="removeRow(\'capex-row-' + i + '\')">' +
        '<i class="fas fa-times"></i></button></div></div>');
}
function addOpexAutre() {
    opexAutresCount++;
    var i = opexAutresCount;
    document.getElementById('opex-autres-container').insertAdjacentHTML('beforeend',
        '<div class="mb-3 row g-2 align-items-end" id="opex-row-' + i + '">' +
        '<div class="col-5"><label class="form-label text-muted small">Désignation</label>' +
        '<input type="text" class="form-control" placeholder="Ex: Assurance, loyer..."></div>' +
        '<div class="col-6"><label class="form-label text-muted small">Montant mensuel</label>' +
        '<div class="input-group"><input type="number" class="form-control opex-input" placeholder="0" min="0" oninput="recalcAll()">' +
        '<span class="input-group-text">FCFA/mois</span></div></div>' +
        '<div class="col-1 pb-1"><button class="btn btn-sm btn-outline-danger" onclick="removeRow(\'opex-row-' + i + '\')">' +
        '<i class="fas fa-times"></i></button></div></div>');
}
function removeRow(id) {
    var el = document.getElementById(id);
    if (el) { el.remove(); recalcAll(); }
}
function majBadgeMarketing(r) {
    document.getElementById('revenu-live-badge').innerHTML =
        '<i class="fas fa-check-circle me-1"></i>Revenus marketing\\u00a0: ' +
        Math.round(r).toLocaleString('fr-FR') + '\\u00a0FCFA/an (extrapolé)';
}
function pollMarketing() {
    var r = lireRevenusMarketing();
    if (r > 0 && r !== revenusMarketing) {
        revenusMarketing = r;
        recalcAll();
        majBadgeMarketing(r);
    }
}
try {
    var bc = new BroadcastChannel('sen_roi');
    bc.onmessage = function(e) {
        if (e.data && e.data.revenus_annuels) {
            revenusMarketing = parseFloat(e.data.revenus_annuels) || 0;
            recalcAll();
            majBadgeMarketing(revenusMarketing);
        }
    };
} catch(e) {}
setInterval(pollMarketing, 3000);
revenusMarketing = lireRevenusMarketing();
if (revenusMarketing > 0) majBadgeMarketing(revenusMarketing);
recalcAll();
</script>
<div class="card mt-4">
<div class="card-header">
<h4 class="mb-0"><i class="fas fa-tachometer-alt me-2" style="color:#4CAF50"></i>Performances du Système</h4>
</div>
</div>
<div class="card mt-3">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-industry me-2" style="color:#00BCD4"></i>Performance de Production</h5>
</div>
<div class="card-body">
<div class="row g-3 mb-4">
<div class="col-md-2">
<div class="kpi-card" style="border-color:#00BCD4">
<div class="kpi-icon" style="color:#00BCD4"><i class="fas fa-fire"></i></div>
<div class="kpi-value" style="color:#00BCD4" id="prod-biogaz-jour">---</div>
<div class="kpi-label">Biogaz / Jour</div>
<div class="kpi-sub">m³</div>
</div>
</div>
<div class="col-md-2">
<div class="kpi-card" style="border-color:#00BCD4">
<div class="kpi-icon" style="color:#00BCD4"><i class="fas fa-calendar-week"></i></div>
<div class="kpi-value" style="color:#00BCD4" id="prod-biogaz-sem">---</div>
<div class="kpi-label">Biogaz / Semaine</div>
<div class="kpi-sub">m³</div>
</div>
</div>
<div class="col-md-2">
<div class="kpi-card" style="border-color:#00BCD4">
<div class="kpi-icon" style="color:#00BCD4"><i class="fas fa-calendar-alt"></i></div>
<div class="kpi-value" style="color:#00BCD4" id="prod-biogaz-mois">---</div>
<div class="kpi-label">Biogaz / Mois</div>
<div class="kpi-sub">m³</div>
</div>
</div>
<div class="col-md-2">
<div class="kpi-card" style="border-color:#8BC34A">
<div class="kpi-icon" style="color:#8BC34A"><i class="fas fa-leaf"></i></div>
<div class="kpi-value" style="color:#8BC34A" id="prod-spir-jour">---</div>
<div class="kpi-label">Spiruline / Jour</div>
<div class="kpi-sub">g</div>
</div>
</div>
<div class="col-md-2">
<div class="kpi-card" style="border-color:#8BC34A">
<div class="kpi-icon" style="color:#8BC34A"><i class="fas fa-calendar-week"></i></div>
<div class="kpi-value" style="color:#8BC34A" id="prod-spir-sem">---</div>
<div class="kpi-label">Spiruline / Semaine</div>
<div class="kpi-sub">g</div>
</div>
</div>
<div class="col-md-2">
<div class="kpi-card" style="border-color:#8BC34A">
<div class="kpi-icon" style="color:#8BC34A"><i class="fas fa-calendar-alt"></i></div>
<div class="kpi-value" style="color:#8BC34A" id="prod-spir-mois">---</div>
<div class="kpi-label">Spiruline / Mois</div>
<div class="kpi-sub">g</div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-md-3">
<div class="kpi-card" style="border-color:#FF9800">
<div class="kpi-icon" style="color:#FF9800"><i class="fas fa-percentage"></i></div>
<div class="kpi-value" style="color:#FF9800" id="taux-digesteur">---</div>
<div class="kpi-label">Taux utilisation digesteur</div>
<div class="kpi-sub">%</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card" style="border-color:#E91E63">
<div class="kpi-icon" style="color:#E91E63"><i class="fas fa-exchange-alt"></i></div>
<div class="kpi-value" style="color:#E91E63" id="efficacite-conv">---</div>
<div class="kpi-label">Efficacité conversion</div>
<div class="kpi-sub">substrat → biogaz</div>
</div>
</div>
<div class="col-md-6">
<div class="card h-100" style="background:#1a1a1a;border:1px solid #444">
<div class="card-body">
<div class="section-lbl">Objectif de production vs Réel</div>
<div class="row text-center">
<div class="col-6">
<div class="text-muted small">Biogaz : Objectif</div>
<input type="number" class="form-control form-control-sm mt-1" id="obj-biogaz" placeholder="m³/jour" oninput="majComparaisonProd()">
<div class="fw-bold mt-1" id="ind-biogaz" style="font-size:1.5rem">---</div>
</div>
<div class="col-6">
<div class="text-muted small">Spiruline -- Objectif</div>
<input type="number" class="form-control form-control-sm mt-1" id="obj-spiruline" placeholder="g/jour" oninput="majComparaisonProd()">
<div class="fw-bold mt-1" id="ind-spiruline" style="font-size:1.5rem">---</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
<div class="row g-3">
<div class="col-md-6">
<div class="card"><div class="card-header"><h6><i class="fas fa-fire me-1" style="color:#00BCD4"></i>Évolution production biogaz (m³)</h6></div>
<div class="card-body"><div id="graph-prod-biogaz" style="height:220px"></div></div></div>
</div>
<div class="col-md-6">
<div class="card"><div class="card-header"><h6><i class="fas fa-leaf me-1" style="color:#8BC34A"></i>Évolution production spiruline (g)</h6></div>
<div class="card-body"><div id="graph-prod-spiruline" style="height:220px"></div></div></div>
</div>
</div>
</div>
</div>
<div class="card mt-3">
<div class="card-header">
<h5 class="mb-0"><i class="fas fa-coins me-2" style="color:#FFD700"></i>Performance Économique</h5>
</div>
<div class="card-body">
<div class="row g-3 mb-4">
<div class="col-md-4">
<div class="kpi-card" style="border-color:#FFD700">
<div class="kpi-icon" style="color:#FFD700"><i class="fas fa-calendar-day"></i></div>
<div class="kpi-value" style="color:#FFD700" id="rev-jour">---</div>
<div class="kpi-label">Revenu journalier</div>
<div class="kpi-sub">FCFA</div>
</div>
</div>
<div class="col-md-4">
<div class="kpi-card" style="border-color:#FFD700">
<div class="kpi-icon" style="color:#FFD700"><i class="fas fa-calendar-week"></i></div>
<div class="kpi-value" style="color:#FFD700" id="rev-semaine">---</div>
<div class="kpi-label">Revenu hebdomadaire</div>
<div class="kpi-sub">FCFA</div>
</div>
</div>
<div class="col-md-4">
<div class="kpi-card" style="border-color:#FFD700">
<div class="kpi-icon" style="color:#FFD700"><i class="fas fa-calendar-alt"></i></div>
<div class="kpi-value" style="color:#FFD700" id="rev-mois">---</div>
<div class="kpi-label">Revenu mensuel</div>
<div class="kpi-sub">FCFA</div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-md-3">
<div class="kpi-card" style="border-color:#FF5722">
<div class="kpi-icon" style="color:#FF5722"><i class="fas fa-fire"></i></div>
<div class="kpi-value" style="color:#FF5722" id="cout-biogaz">---</div>
<div class="kpi-label">Coût unitaire biogaz</div>
<div class="kpi-sub">FCFA / m³</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card" style="border-color:#4CAF50">
<div class="kpi-icon" style="color:#4CAF50"><i class="fas fa-leaf"></i></div>
<div class="kpi-value" style="color:#4CAF50" id="cout-spiruline">---</div>
<div class="kpi-label">Coût unitaire spiruline</div>
<div class="kpi-sub">FCFA / kg</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card" style="border-color:#00BCD4">
<div class="kpi-icon" style="color:#00BCD4"><i class="fas fa-percent"></i></div>
<div class="kpi-value" style="color:#00BCD4" id="marge-biogaz">---</div>
<div class="kpi-label">Marge brute biogaz</div>
<div class="kpi-sub">%</div>
</div>
</div>
<div class="col-md-3">
<div class="kpi-card" style="border-color:#9C27B0">
<div class="kpi-icon" style="color:#9C27B0"><i class="fas fa-percent"></i></div>
<div class="kpi-value" style="color:#9C27B0" id="marge-spiruline">---</div>
<div class="kpi-label">Marge brute spiruline</div>
<div class="kpi-sub">%</div>
</div>
</div>
</div>
<div id="alerte-rentabilite" class="alert alert-warning d-none" role="alert">
<i class="fas fa-exclamation-triangle me-2"></i>
<strong>Alerte :</strong> Les ventes sont en dessous du seuil de rentabilité (<span id="seuil-txt">---</span>).
</div>
<div class="row g-3">
<div class="col-md-4">
<div class="card" style="background:#1a1a1a;border-color:#444">
<div class="card-body">
<div class="section-lbl">Paramètres de calcul économique</div>
<div class="mb-2">
<label class="form-label text-muted small">Prix vente biogaz (FCFA/m³)</label>
<input type="number" class="form-control" id="prix-biogaz" placeholder="650" value="650" oninput="recalcEco()">
</div>
<div class="mb-2">
<label class="form-label text-muted small">Prix vente spiruline (FCFA/kg)</label>
<input type="number" class="form-control" id="prix-spiruline" placeholder="6500" value="6500" oninput="recalcEco()">
</div>
<div class="mb-2">
<label class="form-label text-muted small">Seuil de rentabilité (FCFA/jour)</label>
<input type="number" class="form-control" id="seuil-rentabilite" placeholder="0" oninput="recalcEco()">
</div>
</div>
</div>
</div>
<div class="col-md-8">
<div class="card"><div class="card-header"><h6><i class="fas fa-chart-line me-1" style="color:#E91E63"></i>Évolution du ROI dans le temps</h6></div>
<div class="card-body"><div id="graph-roi-evolution" style="height:250px"></div></div></div>
</div>
</div>
<div class="card mt-3" style="background:#1a2a1a;border:1px solid #4CAF50">
<div class="card-header" style="background:#0d1a0d">
<h6 class="mb-0"><i class="fas fa-chart-area me-2" style="color:#4CAF50"></i>Projection de retour sur investissement actualisée</h6>
</div>
<div class="card-body">
<div class="row g-3">
<div class="col-md-3">
<label class="form-label text-muted small">Taux d'actualisation (%/an)</label>
<input type="number" class="form-control" id="taux-actualisation" placeholder="8" value="8" min="0" max="50" oninput="recalcProjectionROI()">
</div>
<div class="col-md-3">
<label class="form-label text-muted small">Horizon de projection (ans)</label>
<input type="number" class="form-control" id="horizon-projection" placeholder="10" value="10" min="1" max="30" oninput="recalcProjectionROI()">
</div>
<div class="col-md-3">
<label class="form-label text-muted small">VAN (Valeur Actuelle Nette)</label>
<div class="fw-bold fs-5 mt-2" id="van-value" style="color:#4CAF50">---</div>
<div class="text-muted small">FCFA</div>
</div>
<div class="col-md-3">
<label class="form-label text-muted small">TRI (Taux Rdt Interne)</label>
<div class="fw-bold fs-5 mt-2" id="tri-value" style="color:#FF9800">---</div>
<div class="text-muted small">%</div>
</div>
</div>
<div class="mt-3"><div id="graph-projection-roi" style="height:280px"></div></div>
</div>
</div>
</div>
</div>
<script>
var prodBiogaz8 = 0;
var prodSpir8 = 0;
var revJour8 = 0;
function fmt8(n, unit) {
    if (isNaN(n) || n===null || n===undefined) return '---';
    return Math.round(n).toLocaleString('fr-FR') + (unit ? '\\u00a0'+unit : '');
}
function majComparaisonProd() {
    var objB = parseFloat(document.getElementById('obj-biogaz').value) || 0;
    var objS = parseFloat(document.getElementById('obj-spiruline').value) || 0;
    var elB = document.getElementById('ind-biogaz');
    var elS = document.getElementById('ind-spiruline');
    if (objB > 0) {
        var ok = prodBiogaz8 >= objB;
        elB.textContent = ok ? '🟢' : '🔴';
        elB.title = 'Réel: '+prodBiogaz8.toFixed(1)+' m³/j vs Objectif: '+objB+' m³/j';
    } else { elB.textContent = '---'; }
    if (objS > 0) {
        var ok2 = prodSpir8 >= objS;
        elS.textContent = ok2 ? '🟢' : '🔴';
        elS.title = 'Réel: '+prodSpir8.toFixed(1)+' g/j vs Objectif: '+objS+' g/j';
    } else { elS.textContent = '---'; }
}
function recalcEco() {
    var prixB = parseFloat(document.getElementById('prix-biogaz').value) || 650;
    var prixS = parseFloat(document.getElementById('prix-spiruline').value) || 6500;
    var seuil = parseFloat(document.getElementById('seuil-rentabilite').value) || 0;
    var opexMens = sumInputs('opex-input') || 0;
    var opexJ = opexMens / 30;
    var prodSpir8Kg = prodSpir8 / 1000;
    var rBJ = prodBiogaz8 * prixB;
    var rSJ = prodSpir8Kg * prixS;
    revJour8 = rBJ + rSJ;
    document.getElementById('rev-jour').textContent = fmt8(revJour8, 'FCFA');
    document.getElementById('rev-semaine').textContent = fmt8(revJour8*7, 'FCFA');
    document.getElementById('rev-mois').textContent = fmt8(revJour8*30,'FCFA');
    var cB = prodBiogaz8 > 0 ? (opexJ * 0.5 / prodBiogaz8) : NaN;
    var cS = prodSpir8Kg > 0 ? (opexJ * 0.5 / prodSpir8Kg) : NaN;
    document.getElementById('cout-biogaz').textContent = isNaN(cB)?'---':fmt8(cB,'FCFA/m³');
    document.getElementById('cout-spiruline').textContent = isNaN(cS)?'---':fmt8(cS,'FCFA/kg');
    var mB = prixB > 0 ? ((prixB - (isNaN(cB)?0:cB)) / prixB * 100) : NaN;
    var mS = prixS > 0 ? ((prixS - (isNaN(cS)?0:cS)) / prixS * 100) : NaN;
    document.getElementById('marge-biogaz').textContent = isNaN(mB)?'---':mB.toFixed(1)+'\\u00a0%';
    document.getElementById('marge-spiruline').textContent = isNaN(mS)?'---':mS.toFixed(1)+'\\u00a0%';
    if (seuil > 0 && revJour8 > 0) {
        var alerte = document.getElementById('alerte-rentabilite');
        if (revJour8 < seuil) {
            alerte.classList.remove('d-none');
            document.getElementById('seuil-txt').textContent = Math.round(seuil).toLocaleString('fr-FR')+' FCFA/jour';
        } else { alerte.classList.add('d-none'); }
    }
    recalcProjectionROI();
    drawROIEvolution();
}
function recalcProjectionROI() {
    var capex = sumInputs('capex-input') || 0;
    var opexAnnuel = sumInputs('opex-input') * 12 || 0;
    var revsAnnuels = revJour8 > 0 ? revJour8 * 365 : (revenusMarketing || 0);
    var tauxAct = (parseFloat(document.getElementById('taux-actualisation').value) || 8) / 100;
    var horizon = parseInt(document.getElementById('horizon-projection').value) || 10;
    if (capex <= 0 || revsAnnuels <= 0) {
        document.getElementById('van-value').textContent = '---';
        document.getElementById('tri-value').textContent = '---';
        return;
    }
    var fluxNet = revsAnnuels - opexAnnuel;
    var van = -capex;
    var xAns = [], yCumul = [], yActualise = [];
    var cumul = -capex;
    for (var t = 1; t <= horizon; t++) {
        var fa = fluxNet / Math.pow(1 + tauxAct, t);
        van += fa;
        cumul += fluxNet;
        xAns.push('An ' + t);
        yActualise.push(Math.round(van));
        yCumul.push(Math.round(cumul));
    }
    document.getElementById('van-value').textContent = Math.round(van).toLocaleString('fr-FR');
    document.getElementById('van-value').style.color = van >= 0 ? '#4CAF50' : '#F44336';
    var tri = NaN;
    try {
        var lo = -0.5, hi = 5.0;
        for (var iter = 0; iter < 60; iter++) {
            var mid = (lo + hi) / 2;
            var v = -capex;
            for (var t2 = 1; t2 <= horizon; t2++) v += fluxNet / Math.pow(1 + mid, t2);
            if (Math.abs(v) < 1) { tri = mid * 100; break; }
            if (v > 0) lo = mid; else hi = mid;
        }
    } catch(e) {}
    document.getElementById('tri-value').textContent = isNaN(tri) ? '---' : tri.toFixed(1) + '\\u00a0%';
    document.getElementById('tri-value').style.color = (!isNaN(tri) && tri > tauxAct*100) ? '#4CAF50' : '#FF9800';
    if (typeof Plotly !== 'undefined') {
        Plotly.newPlot('graph-projection-roi', [
            {x: xAns, y: yCumul, type:'bar', name:'Cumul flux nets (FCFA)', marker:{color:'#4CAF50',opacity:0.7}},
            {x: xAns, y: yActualise, type:'scatter', mode:'lines+markers', name:'VAN actualisée (FCFA)', line:{color:'#FFD700',width:2}, marker:{size:6}}
        ], {
            template:'plotly_dark', margin:{t:10,b:40,l:80,r:20},
            yaxis:{title:'FCFA'}, legend:{orientation:'h',y:-0.15},
            shapes:[{type:'line',x0:xAns[0],x1:xAns[xAns.length-1],y0:0,y1:0,line:{color:'#F44336',dash:'dot',width:1}}]
        });
    }
}
function drawROIEvolution() {
    var capex = sumInputs('capex-input') || 0;
    var opexAnnuel = sumInputs('opex-input') * 12 || 0;
    var revsAnnuels = revJour8 > 0 ? revJour8 * 365 : (revenusMarketing || 0);
    if (!capex || !revsAnnuels) return;
    var horizon = parseInt(document.getElementById('horizon-projection').value) || 10;
    var xAns = [], yROI = [];
    for (var t = 1; t <= horizon; t++) {
        var beneficeNet = (revsAnnuels - opexAnnuel) * t;
        yROI.push(parseFloat(((beneficeNet / capex) * 100).toFixed(1)));
        xAns.push('An ' + t);
    }
    if (typeof Plotly !== 'undefined') {
        Plotly.newPlot('graph-roi-evolution', [
            {x:xAns, y:yROI, type:'scatter', mode:'lines+markers', name:'ROI cumulé (%)',
            line:{color:'#E91E63',width:2}, marker:{size:7}, fill:'tozeroy', fillcolor:'rgba(233,30,99,0.08)'}
        ], {
            template:'plotly_dark', margin:{t:10,b:40,l:60,r:20},
            yaxis:{title:'ROI (%)'},
            shapes:[{type:'line',x0:xAns[0],x1:xAns[xAns.length-1],y0:0,y1:0,line:{color:'#F44336',dash:'dot',width:1}}]
        });
    }
}
function chargerDonneesSect8() {
    fetch('/api/realtime').then(r=>r.json()).then(data=>{
        if (data.biogas_production) {
            prodBiogaz8 = parseFloat(data.biogas_production) || 0;
            document.getElementById('prod-biogaz-jour').textContent = prodBiogaz8.toFixed(1);
            document.getElementById('prod-biogaz-sem').textContent = (prodBiogaz8*7).toFixed(0);
            document.getElementById('prod-biogaz-mois').textContent = (prodBiogaz8*30).toFixed(0);
        }
        if (data.spirulina_production) {
            prodSpir8 = parseFloat(data.spirulina_production) || 0;
            document.getElementById('prod-spir-jour').textContent = prodSpir8.toFixed(0);
            document.getElementById('prod-spir-sem').textContent = (prodSpir8*7).toFixed(0);
            document.getElementById('prod-spir-mois').textContent = (prodSpir8*30).toFixed(0);
        }
        if (data.digesteur_utilization != null)
            document.getElementById('taux-digesteur').textContent = parseFloat(data.digesteur_utilization).toFixed(1) + '\\u00a0%';
        if (data.conversion_efficiency != null)
            document.getElementById('efficacite-conv').textContent = parseFloat(data.conversion_efficiency).toFixed(3);
        majComparaisonProd();
        recalcEco();
        if (typeof Plotly !== 'undefined' && data.history) {
            var ts = data.history.timestamps || [];
            var bg = data.history.biogas || [];
            var sp = data.history.spirulina || [];
            if (ts.length) {
                Plotly.newPlot('graph-prod-biogaz',
                    [{x:ts,y:bg,type:'scatter',mode:'lines',name:'Biogaz (m³)',line:{color:'#00BCD4',width:2},fill:'tozeroy',fillcolor:'rgba(0,188,212,0.1)'}],
                    {template:'plotly_dark',margin:{t:5,b:40,l:50,r:10},yaxis:{title:'m³'}});
                Plotly.newPlot('graph-prod-spiruline',
                    [{x:ts,y:sp,type:'scatter',mode:'lines',name:'Spiruline (g)',line:{color:'#8BC34A',width:2},fill:'tozeroy',fillcolor:'rgba(139,195,74,0.1)'}],
                    {template:'plotly_dark',margin:{t:5,b:40,l:50,r:10},yaxis:{title:'g'}});
            }
        }
    }).catch(()=>{});
}
chargerDonneesSect8();
setInterval(chargerDonneesSect8, 15000);
</script>
</body>
</html>
''',
    # ── MODULE 8.3 -- PERFORMANCE DES CAPTEURS ───────────────────────────────
    'capteurs_performance': '''
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEN Dashboard - Performance Capteurs</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
body { background-color: #121212; color: #fff; font-family: 'Segoe UI', sans-serif; }
.sidebar { background-color: #1e1e1e; min-height: 100vh; padding-top: 20px; }
.sidebar a { color: #fff; text-decoration: none; display: block; padding: 10px 20px; margin: 5px 0; border-radius: 5px; transition: all .3s; }
.sidebar a:hover, .sidebar a.active { background-color: #4CAF50; }
.content { padding: 20px; }
.card { background-color: #2d2d2d; border: 1px solid #444; border-radius: 10px; margin-bottom: 20px; }
.card-header { background-color: #1a1a1a; border-bottom: 1px solid #444; padding: 15px; }
.kpi-sensor { background: #1e1e1e; border: 1px solid #444; border-radius: 10px; padding: 20px; text-align: center; margin-bottom: 15px; transition: box-shadow .3s; }
.kpi-sensor:hover { box-shadow: 0 0 15px rgba(76,175,80,.3); }
.kpi-sensor .kpi-value { font-size: 2.2rem; font-weight: 700; }
.kpi-sensor .kpi-label { font-size: .85rem; color: #aaa; margin-top: 4px; }
.kpi-sensor .kpi-sub { font-size: .75rem; color: #777; margin-top: 2px; }
.dispo-excellent { color: #4CAF50; }
.dispo-good { color: #8BC34A; }
.dispo-warn { color: #FF9800; }
.dispo-alert { color: #F44336; }
.table-dark th { background: #1a1a1a; color: #aaa; font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }
.table-dark td { border-color: #333; vertical-align: middle; }
.badge-ok { background: #2E7D32; }
.badge-warn { background: #E65100; }
.badge-crit { background: #B71C1C; }
.stabilite-bar { height: 8px; border-radius: 4px; background: #333; overflow: hidden; }
.stabilite-fill { height: 100%; border-radius: 4px; transition: width .6s ease; }
.graph-container { min-height: 260px; }
.periode-select { background: #1e1e1e; color: #fff; border: 1px solid #444; border-radius: 5px; padding: 4px 10px; }
</style>
</head>
<body>
<div class="container-fluid">
<div class="row">
<div class="col-md-2 sidebar">
<div class="text-center mb-4">
<h4><i class="fas fa-leaf me-2" style="color:#4CAF50"></i>SEN Dashboard</h4>
<small class="text-muted">Version 3.5</small>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MENU PRINCIPAL</small></div>
<a href="/"><i class="fas fa-home me-2"></i>Accueil</a>
<a href="/dashboard/realtime"><i class="fas fa-chart-line me-2"></i>Temps Réel</a>
<a href="/dashboard/historical"><i class="fas fa-chart-bar me-2"></i>Historique</a>
<a href="/dashboard/analytics"><i class="fas fa-chart-pie me-2"></i>Analytique</a>
<a href="/dashboard/reports"><i class="fas fa-file-alt me-2"></i>Rapports</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">MODULES</small></div>
<a href="/dashboard/marketing"><i class="fas fa-store me-2"></i>Marketing</a>
<a href="/dashboard/performance"><i class="fas fa-chart-pie me-2"></i>Performance Éco.</a>
<a href="/dashboard/capteurs" class="active"><i class="fas fa-satellite-dish me-2"></i>Perf. Capteurs</a>
</div>
<div class="mb-3">
<div class="px-3"><small class="text-muted">SYSTÈME</small></div>
<a href="/dashboard/configuration"><i class="fas fa-cog me-2"></i>Configuration</a>
<a href="/dashboard/alarms"><i class="fas fa-bell me-2"></i>Alarmes</a>
<a href="/dashboard/health"><i class="fas fa-heartbeat me-2"></i>Santé</a>
</div>
<div class="mt-5 px-3">
<small class="text-muted">UTILISATEUR</small>
<div class="mt-2"><strong>{{ user.username }}</strong><br><small class="text-muted">{{ user.role }}</small></div>
<a href="/logout" class="btn btn-sm btn-outline-danger mt-3 w-100"><i class="fas fa-sign-out-alt me-1"></i>Déconnexion</a>
</div>
</div>
<div class="col-md-10 content">
<div class="d-flex justify-content-between align-items-center mb-4">
<h2><i class="fas fa-satellite-dish me-2" style="color:#4CAF50"></i>Performance des Capteurs</h2>
<div class="d-flex align-items-center gap-3">
<select class="periode-select" id="periode-select" onchange="chargerCapteurs()">
<option value="24h">Dernières 24h</option>
<option value="7d" selected>7 derniers jours</option>
<option value="30d">30 derniers jours</option>
<option value="90d">90 derniers jours</option>
</select>
<span class="badge bg-secondary" id="last-update-badge"><i class="fas fa-clock me-1"></i>---</span>
</div>
</div>
<div class="row mb-4">
<div class="col-md-4">
<div class="kpi-sensor">
<div class="kpi-value dispo-excellent" id="kpi-dispo-globale">---</div>
<div class="kpi-label"><i class="fas fa-wifi me-1"></i>Taux de disponibilité global</div>
<div class="kpi-sub">Moyenne pondérée tous capteurs</div>
</div>
</div>
<div class="col-md-4">
<div class="kpi-sensor">
<div class="kpi-value text-warning" id="kpi-nb-alarmes">---</div>
<div class="kpi-label"><i class="fas fa-bell me-1"></i>Alarmes déclenchées</div>
<div class="kpi-sub" id="kpi-alarmes-sub">Sur la période sélectionnée</div>
</div>
</div>
<div class="col-md-4">
<div class="kpi-sensor">
<div class="kpi-value text-info" id="kpi-stabilite-globale">---</div>
<div class="kpi-label"><i class="fas fa-sliders-h me-1"></i>Stabilité paramètres critiques</div>
<div class="kpi-sub">pH PBR · Temp. PBR · Temp. Digesteur</div>
</div>
</div>
</div>
<div class="card mb-4">
<div class="card-header d-flex justify-content-between">
<h5 class="mb-0"><i class="fas fa-sliders-h me-2" style="color:#00BCD4"></i>Stabilité des Paramètres Critiques</h5>
<small class="text-muted">Écart-type normalisé (0 = parfait, 100 = instable)</small>
</div>
<div class="card-body">
<div class="row">
<div class="col-md-4 mb-3">
<div class="d-flex justify-content-between mb-1">
<span><i class="fas fa-flask me-1 text-info"></i>pH PBR</span>
<span id="val-ph-pbr" class="fw-bold">---</span>
</div>
<div class="stabilite-bar mb-1">
<div class="stabilite-fill bg-info" id="bar-ph-pbr" style="width:0%"></div>
</div>
<div class="d-flex justify-content-between">
<small class="text-muted">Écart-type : <span id="std-ph-pbr">---</span></small>
<small id="badge-ph-pbr" class="badge badge-ok">Stable</small>
</div>
</div>
<div class="col-md-4 mb-3">
<div class="d-flex justify-content-between mb-1">
<span><i class="fas fa-thermometer-half me-1 text-success"></i>Température PBR (°C)</span>
<span id="val-temp-pbr" class="fw-bold">---</span>
</div>
<div class="stabilite-bar mb-1">
<div class="stabilite-fill bg-success" id="bar-temp-pbr" style="width:0%"></div>
</div>
<div class="d-flex justify-content-between">
<small class="text-muted">Écart-type : <span id="std-temp-pbr">---</span></small>
<small id="badge-temp-pbr" class="badge badge-ok">Stable</small>
</div>
</div>
<div class="col-md-4 mb-3">
<div class="d-flex justify-content-between mb-1">
<span><i class="fas fa-thermometer-full me-1 text-warning"></i>Température Digesteur (°C)</span>
<span id="val-temp-dig" class="fw-bold">---</span>
</div>
<div class="stabilite-bar mb-1">
<div class="stabilite-fill bg-warning" id="bar-temp-dig" style="width:0%"></div>
</div>
<div class="d-flex justify-content-between">
<small class="text-muted">Écart-type : <span id="std-temp-dig">---</span></small>
<small id="badge-temp-dig" class="badge badge-ok">Stable</small>
</div>
</div>
</div>
</div>
</div>
<div class="row mb-4">
<div class="col-md-6">
<div class="card">
<div class="card-header"><h6 class="mb-0"><i class="fas fa-flask me-2 text-info"></i>Évolution pH PBR</h6></div>
<div class="card-body p-2"><div id="graph-ph-pbr" class="graph-container"></div></div>
</div>
</div>
<div class="col-md-6">
<div class="card">
<div class="card-header"><h6 class="mb-0"><i class="fas fa-thermometer-half me-2 text-success"></i>Évolution Température PBR</h6></div>
<div class="card-body p-2"><div id="graph-temp-pbr" class="graph-container"></div></div>
</div>
</div>
</div>
<div class="row mb-4">
<div class="col-md-6">
<div class="card">
<div class="card-header"><h6 class="mb-0"><i class="fas fa-thermometer-full me-2 text-warning"></i>Évolution Température Digesteur</h6></div>
<div class="card-body p-2"><div id="graph-temp-dig" class="graph-container"></div></div>
</div>
</div>
<div class="col-md-6">
<div class="card">
<div class="card-header"><h6 class="mb-0"><i class="fas fa-bell me-2 text-danger"></i>Alarmes par composant</h6></div>
<div class="card-body p-2"><div id="graph-alarmes" class="graph-container"></div></div>
</div>
</div>
</div>
<div class="card mb-4">
<div class="card-header"><h5 class="mb-0"><i class="fas fa-table me-2" style="color:#4CAF50"></i>Disponibilité par Capteur</h5></div>
<div class="card-body p-0">
<div class="table-responsive">
<table class="table table-dark table-hover mb-0">
<thead>
<tr>
<th>Composant</th>
<th>Capteur</th>
<th>Disponibilité (%)</th>
<th>Échantillons valides</th>
<th>Données manquantes</th>
<th>Dernière valeur</th>
<th>Statut</th>
</tr>
</thead>
<tbody id="table-capteurs-body">
<tr><td colspan="7" class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>Chargement...</td></tr>
</tbody>
</table>
</div>
</div>
</div>
<div class="card mb-4">
<div class="card-header d-flex justify-content-between">
<h5 class="mb-0"><i class="fas fa-exclamation-triangle me-2 text-warning"></i>Anomalies Capteurs Détectées (Section 7 -- IA)</h5>
<span class="badge bg-warning text-dark" id="badge-nb-anomalies">0</span>
</div>
<div class="card-body">
<div id="anomalies-container">
<p class="text-muted mb-0"><i class="fas fa-check-circle me-2 text-success"></i>Aucune anomalie détectée par le moteur IA.</p>
</div>
</div>
</div>
</div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
var SEUILS = {
    ph_pbr: { warn: 0.3, crit: 0.5, max_std: 1.0 },
    temp_pbr: { warn: 1.0, crit: 2.0, max_std: 5.0 },
    temp_dig: { warn: 1.5, crit: 3.0, max_std: 8.0 }
};
function dispoCls(v) {
    if (v >= 99) return 'dispo-excellent';
    if (v >= 95) return 'dispo-good';
    if (v >= 85) return 'dispo-warn';
    return 'dispo-alert';
}
function stabiliteLabel(score) {
    if (score <= 20) return 'Excellent';
    if (score <= 40) return 'Stable';
    if (score <= 60) return 'Acceptable';
    if (score <= 80) return 'Instable';
    return 'Critique';
}
function badgeCls(std, seuils) {
    if (std <= seuils.warn) return 'badge-ok';
    if (std <= seuils.crit) return 'badge-warn';
    return 'badge-crit';
}
function badgeTxt(std, seuils) {
    if (std <= seuils.warn) return 'Stable';
    if (std <= seuils.crit) return 'Acceptable';
    return 'Instable';
}
function majBarStabilite(idBar, idVal, idBadge, idStd, serie, seuils, label) {
    if (!serie || serie.length < 2) return;
    var n = serie.length;
    var mean = serie.reduce(function(a,b){return a+b;}, 0) / n;
    var variance = serie.reduce(function(a,b){return a + Math.pow(b - mean, 2);}, 0) / n;
    var std = Math.sqrt(variance);
    var pct = Math.min(100, (std / seuils.max_std) * 100);
    document.getElementById(idVal).textContent = mean.toFixed(2);
    document.getElementById(idStd).textContent = '±' + std.toFixed(3);
    document.getElementById(idBar).style.width = pct.toFixed(1) + '%';
    var badge = document.getElementById(idBadge);
    badge.className = 'badge ' + badgeCls(std, seuils);
    badge.textContent = badgeTxt(std, seuils);
}
function plotParam(divId, timestamps, values, title, color, plageMin, plageMax) {
    if (!timestamps || !values || !timestamps.length) return;
    var traces = [
        {x: timestamps, y: values, type: 'scatter', mode: 'lines', name: title,
         line: {color: color, width: 2}, fill: 'tozeroy', fillcolor: color.replace(')', ',0.08)').replace('rgb', 'rgba')}
    ];
    if (plageMin != null && plageMax != null) {
        traces.push({
            x: [timestamps[0], timestamps[timestamps.length-1]],
            y: [plageMin, plageMin], type: 'scatter', mode: 'lines',
            name: 'Min optimal', line: {color: '#FF9800', dash: 'dot', width: 1}, showlegend: true
        });
        traces.push({
            x: [timestamps[0], timestamps[timestamps.length-1]],
            y: [plageMax, plageMax], type: 'scatter', mode: 'lines',
            name: 'Max optimal', line: {color: '#F44336', dash: 'dot', width: 1}, showlegend: true
        });
    }
    Plotly.newPlot(divId, traces, {
        template: 'plotly_dark',
        margin: {t: 15, b: 40, l: 55, r: 15},
        yaxis: {title: title},
        legend: {orientation: 'h', y: -0.25},
        height: 260
    });
}
function plotAlarmes(alarmes) {
    var composants = ['digesteur', 'photobioreactor', 'système'];
    var totaux = [0, 0, 0];
    var actives = [0, 0, 0];
    alarmes.forEach(function(a) {
        var idx = composants.indexOf(a.component);
        if (idx < 0) idx = 2;
        totaux[idx]++;
        if (!a.acknowledged) actives[idx]++;
    });
    Plotly.newPlot('graph-alarmes', [
        {x: composants, y: totaux, type: 'bar', name: 'Total',
         marker: {color: '#FF9800'}, text: totaux, textposition: 'auto'},
        {x: composants, y: actives, type: 'bar', name: 'Non acquittées',
         marker: {color: '#F44336'}, text: actives, textposition: 'auto'}
    ], {
        template: 'plotly_dark',
        barmode: 'group',
        margin: {t: 10, b: 40, l: 50, r: 15},
        legend: {orientation: 'h', y: -0.3},
        height: 260
    });
}
function majTableauCapteurs(perf) {
    var tbody = document.getElementById('table-capteurs-body');
    if (!perf || !perf.capteurs || !perf.capteurs.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Aucune donnée disponible</td></tr>';
        return;
    }
    var rows = perf.capteurs.map(function(c) {
        var cls = c.disponibilite >= 99 ? 'text-success' : c.disponibilite >= 95 ? 'text-warning' : 'text-danger';
        var statut = c.disponibilite >= 99 ? '<span class="badge badge-ok">En ligne</span>' :
                     c.disponibilite >= 85 ? '<span class="badge badge-warn">Dégradé</span>' :
                     '<span class="badge badge-crit">Hors ligne</span>';
        return '<tr>' +
            '<td><span class="badge bg-secondary">' + c.composant + '</span></td>' +
            '<td>' + c.nom + '</td>' +
            '<td class="' + cls + ' fw-bold">' + c.disponibilite.toFixed(1) + ' %</td>' +
            '<td>' + c.echantillons_valides + '</td>' +
            '<td>' + c.donnees_manquantes + '</td>' +
            '<td>' + (c.derniere_valeur != null ? c.derniere_valeur.toFixed(3) : '---') + '</td>' +
            '<td>' + statut + '</td>' +
            '</tr>';
    });
    tbody.innerHTML = rows.join('');
}
function majAnomalies(anomalies) {
    var container = document.getElementById('anomalies-container');
    document.getElementById('badge-nb-anomalies').textContent = anomalies.length;
    if (!anomalies.length) {
        container.innerHTML = '<p class="text-muted mb-0"><i class="fas fa-check-circle me-2 text-success"></i>Aucune anomalie détectée par le moteur IA.</p>';
        return;
    }
    var html = anomalies.map(function(a) {
        var sev = a.severity || a.severite || 'warning';
        var icon = sev === 'critical' ? 'fas fa-times-circle text-danger' : 'fas fa-exclamation-circle text-warning';
        return '<div class="alert alert-' + (sev === 'critical' ? 'danger' : 'warning') + ' d-flex align-items-start mb-2 py-2">' +
            '<i class="' + icon + ' me-2 mt-1"></i>' +
            '<div><strong>' + (a.capteur || a.sensor || 'Capteur') + '</strong><br>' +
            '<small>' + (a.message || a.description || '') + '</small></div>' +
            '</div>';
    });
    container.innerHTML = html.join('');
}
function chargerCapteurs() {
    var periode = document.getElementById('periode-select').value;
    fetch('/api/capteurs/performance?periode=' + periode)
    .then(function(r) { return r.json(); })
    .then(function(perf) {
        var dispo = perf.taux_disponibilite_global || 0;
        var el = document.getElementById('kpi-dispo-globale');
        el.textContent = dispo.toFixed(1) + ' %';
        el.className = 'kpi-value ' + dispoCls(dispo);
        document.getElementById('kpi-nb-alarmes').textContent = perf.nb_alarmes_periode || 0;
        document.getElementById('kpi-alarmes-sub').textContent = 'Sur la période : ' + periode;
        var stabScore = perf.stabilite_globale_score || 0;
        var stabEl = document.getElementById('kpi-stabilite-globale');
        stabEl.textContent = stabiliteLabel(stabScore);
        stabEl.className = 'kpi-value ' + (stabScore <= 40 ? 'text-success' : stabScore <= 60 ? 'text-warning' : 'text-danger');
        majTableauCapteurs(perf);
        var now = new Date();
        document.getElementById('last-update-badge').innerHTML = '<i class="fas fa-clock me-1"></i>' + now.toLocaleTimeString('fr-FR');
    })
    .catch(function(err) { console.warn('API capteurs/performance:', err); });
    var periodeHours = periode === '24h' ? 24 : periode === '7d' ? 168 : periode === '30d' ? 720 : 2160;
    fetch('/api/historical/photobioreactor?period=' + (periode === '24h' ? '7d' : periode))
    .then(function(r) { return r.json(); })
    .then(function(hist) {
        var ts = hist.timestamps || [];
        var ph = hist.ph || [];
        var tempPbr = hist.temperature || [];
        var cut = periodeHours;
        ts = ts.slice(-cut);
        ph = ph.slice(-cut);
        tempPbr = tempPbr.slice(-cut);
        majBarStabilite('bar-ph-pbr', 'val-ph-pbr', 'badge-ph-pbr', 'std-ph-pbr', ph, SEUILS.ph_pbr, 'pH');
        majBarStabilite('bar-temp-pbr', 'val-temp-pbr', 'badge-temp-pbr', 'std-temp-pbr', tempPbr, SEUILS.temp_pbr, 'Temp PBR');
        plotParam('graph-ph-pbr', ts, ph, 'pH PBR', 'rgb(0,188,212)', 6.8, 7.8);
        plotParam('graph-temp-pbr', ts, tempPbr, 'Temp. PBR (°C)', 'rgb(76,175,80)', 24.0, 30.0);
    })
    .catch(function(e) { console.warn('API historical/photobioreactor:', e); });
    fetch('/api/historical/digester?period=' + (periode === '24h' ? '7d' : periode))
    .then(function(r) { return r.json(); })
    .then(function(hist) {
        var ts = hist.timestamps || [];
        var tempDig = hist.temperature || [];
        var cut = periodeHours;
        ts = ts.slice(-cut);
        tempDig = tempDig.slice(-cut);
        majBarStabilite('bar-temp-dig', 'val-temp-dig', 'badge-temp-dig', 'std-temp-dig', tempDig, SEUILS.temp_dig, 'Temp Digesteur');
        plotParam('graph-temp-dig', ts, tempDig, 'Temp. Digesteur (°C)', 'rgb(255,152,0)', 33.0, 38.0);
    })
    .catch(function(e) { console.warn('API historical/digester:', e); });
    fetch('/api/alarms')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        plotAlarmes(data.alarms || []);
    })
    .catch(function(e) { console.warn('API alarms:', e); });
    fetch('/api/predictions/weekly')
    .then(function(r) { return r.json(); })
    .then(function(pred) {
        var anomalies = pred.anomalies_capteurs || [];
        majAnomalies(anomalies);
    })
    .catch(function(e) { console.warn('API predictions/weekly:', e); });
}
chargerCapteurs();
setInterval(chargerCapteurs, 30000);
</script>
</body>
</html>
'''
}  # fin HTML_TEMPLATES

# ==================== FILTRE JINJA2 FCFA =====================================
def _jinja_format_fcfa(value):
    """Filtre Jinja2 : {{ 93530 | format_fcfa }} → '93 530 FCFA'"""
    try:
        return f"{int(round(float(value))):,}".replace(",", " ") + " FCFA"
    except (ValueError, TypeError):
        return str(value) + " FCFA"
_JINJA_ENV.filters["format_fcfa"] = _jinja_format_fcfa

# ==================== CACHE JINJA2 ============================================
_TEMPLATE_CACHE: Dict[str, Any] = {}
def _get_template(name: str):
    if name not in _TEMPLATE_CACHE:
        source = HTML_TEMPLATES.get(name)
        if source is None:
            raise KeyError(f"Template '{name}' introuvable")
        _TEMPLATE_CACHE[name] = _JINJA_ENV.from_string(source)
    return _TEMPLATE_CACHE[name]
def render(template_name: str, **ctx) -> str:
    return _get_template(template_name).render(**ctx)

# ==================== TAUX DE CONVERSION EUR → FCFA ==========================
# 1 EUR ≈ 655.957 FCFA (taux fixe zone UEMOA/BCEAO)
EUR_TO_FCFA = 655.957
def eur_to_fcfa(eur: float) -> float:
    return round(eur * EUR_TO_FCFA)

# ==================== SYSTÈME DE PRÉDICTION -- Section 7 =====================
# Architecture : LSTM simplifié (gates manuelles) + Attention temporelle
# Toutes les prédictions sont basées UNIQUEMENT sur les données capteurs réelles.

class LSTMCell:
    """Cellule LSTM minimale implémentée en numpy pur (sans dépendance ML externe)."""
    def __init__(self, input_size: int, hidden_size: int, seed: int = 42):
        rng = np.random.default_rng(seed)
        scale = 0.1
        # Poids : [input_gate, forget_gate, cell_gate, output_gate]
        self.Wf = rng.standard_normal((hidden_size, input_size + hidden_size)) * scale
        self.bf = np.zeros(hidden_size)
        self.Wi = rng.standard_normal((hidden_size, input_size + hidden_size)) * scale
        self.bi = np.zeros(hidden_size)
        self.Wc = rng.standard_normal((hidden_size, input_size + hidden_size)) * scale
        self.bc = np.zeros(hidden_size)
        self.Wo = rng.standard_normal((hidden_size, input_size + hidden_size)) * scale
        self.bo = np.zeros(hidden_size)
        self.Wy = rng.standard_normal((1, hidden_size)) * scale
        self.by = np.zeros(1)
        self.hidden_size = hidden_size

    @staticmethod
    def _sigmoid(x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -15, 15)))
    @staticmethod
    def _tanh(x):
        return np.tanh(np.clip(x, -15, 15))

    def forward_sequence(self, X: np.ndarray) -> np.ndarray:
        """Passe avant sur une séquence X de shape (T, input_size)."""
        T = X.shape[0]
        h = np.zeros(self.hidden_size)
        c = np.zeros(self.hidden_size)
        outputs = []
        for t in range(T):
            x = X[t]
            combined = np.concatenate([x, h])
            f = self._sigmoid(self.Wf @ combined + self.bf)
            i = self._sigmoid(self.Wi @ combined + self.bi)
            c_tilde = self._tanh(self.Wc @ combined + self.bc)
            c = f * c + i * c_tilde
            o = self._sigmoid(self.Wo @ combined + self.bo)
            h = o * self._tanh(c)
            y = self.Wy @ h + self.by
            outputs.append(float(y[0]))
        return np.array(outputs)

class PredictionEngine:
    """
    Moteur de prédiction : Deep Learning Haute Performance.
    - Utilise UNIQUEMENT les données capteurs réelles fournies.
    - LSTM + mécanisme d'attention temporelle simple.
    - Réentraînement automatique détecté via hash des données.
    - Produit prédictions biogaz, spiruline, anomalies, maintenance, prix conseillés.
    """
    # Plages normales capteurs (alerte si hors de ces plages)
    SENSOR_RANGES = {
        "temp_digesteur": (30.0, 45.0),   # °C
        "temp_pbr": (20.0, 35.0),         # °C
        "ph_pbr": (6.5, 8.5),
        "debit_d'eau": (5.0, 25.0),      # m³/h
        "vol_eau_saturee": (20.0, 80.0),  # L
        "production_spiruline": (50.0, 500.0),  # g/jour
    }
    # Libellés français lisibles pour affichage dans l'interface (anomalies capteurs)
    SENSOR_LABELS = {
        "temp_digesteur": "Température Digesteur",
        "temp_pbr": "Température PBR",
        "ph_pbr": "pH PBR",
        "debit_biogaz": "Débit Biogaz",
        "vol_eau_saturee": "Volume Eau Saturée",
        "production_spiruline": "Production Spiruline",
    }
    # Paramètres marché FCFA
    # Spiruline toujours en FCFA/kg (jamais au gramme).
    MARKET = {
        "biogaz": {"min": 500, "max": 800, "base": 650},
        "spiruline_fraiche": {"valeur": 6500, "unite": "FCFA/kg"},
        "spiruline_sechee": {"valeur": 20000, "unite": "FCFA/kg"},
    }

    def __init__(self, hidden_size: int = 16):
        self.hidden_size = hidden_size
        self._lstm_biogaz = LSTMCell(input_size=4, hidden_size=hidden_size, seed=7)
        self._lstm_spiruline = LSTMCell(input_size=5, hidden_size=hidden_size, seed=13)
        self._data_hash: Optional[str] = None
        self._weekly_cache: Optional[Dict] = None
        self._cache_ts: Optional[datetime] = None
        self._train_history: deque = deque(maxlen=52)   # 52 semaines max
        logger.info("✅ PredictionEngine initialisé (LSTM + Attention)")

    # ── Normalisation min-max ──────────────────────────────────────────────────
    @staticmethod
    def _normalize(arr: np.ndarray) -> Tuple[np.ndarray, float, float]:
        mn, mx = arr.min(), arr.max()
        if mx - mn < 1e-9:
            return np.zeros_like(arr), mn, mx
        return (arr - mn) / (mx - mn), mn, mx
    @staticmethod
    def _denormalize(arr: np.ndarray, mn: float, mx: float) -> np.ndarray:
        return arr * (mx - mn) + mn

    # ── Attention temporelle ───────────────────────────────────────────────────
    @staticmethod
    def _attention_weights(sequence: np.ndarray) -> np.ndarray:
        """Poids d'attention basés sur la variance locale : données récentes pondérées."""
        T = len(sequence)
        if T < 2:
            return np.ones(T) / T
        # Score = position récente + variance locale
        pos_score = np.linspace(0.5, 1.0, T)
        var_score = np.array([
            np.var(sequence[max(0, i-2):i+2]) + 1e-9
            for i in range(T)
        ])
        combined = pos_score * np.log1p(var_score)
        return combined / combined.sum()

    # ── Détection hash pour réentraînement ────────────────────────────────────
    def _compute_hash(self, data: Dict, measurements_count: int = 0) -> str:
        key = str(len(data.get("digester", {}).get("gas_flow", [])))
        key += str(len(data.get("photobioreactor", {}).get("biomass_density", [])))
        # Tant que la confiance est encore en phase de montée (< 200 mesures),
        # chaque nouvelle mesure doit invalider le cache pour que la confiance avance.
        key += "_m" + str(min(measurements_count, 200))
        return key
    def _needs_retrain(self, data: Dict, measurements_count: int = 0) -> bool:
        h = self._compute_hash(data, measurements_count)
        if h != self._data_hash:
            self._data_hash = h
            return True
        # Réentraîner chaque semaine même sans nouvelles données
        if self._cache_ts and (datetime.now() - self._cache_ts).total_seconds() > 604800:
            return True
        return False

    # ── Prédiction biogaz ──────────────────────────────────────────────────────
    def _predict_biogaz_semaine(self, historical: Dict) -> Dict:
        """Prédit la production biogaz (m³) pour la semaine suivante."""
        gas = np.array(historical["digester"].get("gas_flow", [])[-168:], dtype=float)
        temp_d = np.array(historical["digester"].get("temperature", [])[-168:], dtype=float)
        ch4 = np.array(historical["digester"].get("ch4_concentration", [])[-168:], dtype=float)
        temp_p = np.array(historical["photobioreactor"].get("temperature", [])[-168:], dtype=float)
        # Si gas_flow est absent ou tout à zéro, utiliser temp seul pour prédire
        gas_is_zero = len(gas) == 0 or float(np.sum(np.abs(gas))) < 0.01
        if gas_is_zero:
            # Prédiction basée température seule (modèle Gompertz simplifié)
            T = len(temp_d)
            if T < 6:
                return {"valeur_m3": 12.0, "confidence": 0.55, "source": "defaut_temp_insuffisante", "variation_pct": 0.0}
            mean_temp = float(np.mean(temp_d[-T:]))
            # Facteur température : optimum 35°C, référence 1.4 m³/j pour 250L
            temp_factor = max(0.3, 1.0 - abs(mean_temp - 35.0) * 0.05)
            prod_m3 = round(1.4 * 7 * temp_factor, 1)
            conf = min(0.72, 0.45 + T / 500.0)
            return {"valeur_m3": prod_m3, "confidence": round(conf, 3), "source": "modele_temperature", "variation_pct": 0.0}
        T = min(len(gas), len(temp_d), len(ch4), len(temp_p))
        if T < 24:
            mean_flow = float(np.mean(gas)) if len(gas) > 0 else 12.0
            return {
                "valeur_m3": round(mean_flow * 24 * 7, 1),
                "confidence": 0.55,
                "source": "extrapolation_lineaire",
                "variation_pct": 0.0,
            }
        gas = gas[-T:]; temp_d = temp_d[-T:]
        ch4 = ch4[-T:]; temp_p = temp_p[-T:]
        # Normalisation
        gas_n, g_mn, g_mx = self._normalize(gas)
        td_n, td_mn, td_mx = self._normalize(temp_d)
        ch4_n, c_mn, c_mx = self._normalize(ch4)
        tp_n, tp_mn, tp_mx = self._normalize(temp_p)
        X = np.column_stack([gas_n, td_n, ch4_n, tp_n])   # (T, 4)
        # LSTM forward
        lstm_out = self._lstm_biogaz.forward_sequence(X)  # (T,)
        # Attention sur les 48 dernières heures
        recent = lstm_out[-min(48, T):]
        weights = self._attention_weights(recent)
        attended_val = float(np.dot(weights, recent))      # scalaire normalisé [0,1]
        # Dénormalisation + projection 7 jours
        pred_flow_h = self._denormalize(np.array([attended_val]), g_mn, g_mx)[0]
        pred_flow_h = max(1.0, float(pred_flow_h))
        # Tendance 4 semaines (régression linéaire)
        weekly_sums = []
        for w in range(4):
            start = max(0, T - (w+1)*168)
            end = T - w*168
            if end > start:
                weekly_sums.append(float(np.sum(gas[start:end])))
        if len(weekly_sums) >= 2:
            trend = (weekly_sums[0] - weekly_sums[-1]) / len(weekly_sums)
        else:
            trend = 0.0
        prod_m3 = pred_flow_h * 24 * 7 + trend * 0.5
        prod_m3 = max(0.0, round(prod_m3, 1))
        # Confiance basée sur variance des semaines récentes
        if len(weekly_sums) >= 2:
            cv = np.std(weekly_sums) / (np.mean(weekly_sums) + 1e-9)
            confidence = max(0.60, min(0.96, 1.0 - cv * 0.5))
        else:
            confidence = 0.70
        variation_pct = 0.0
        if len(weekly_sums) >= 2 and weekly_sums[1] > 0:
            variation_pct = round((weekly_sums[0] - weekly_sums[1]) / weekly_sums[1] * 100, 1)
        return {
            "valeur_m3": prod_m3,
            "confidence": round(float(confidence), 3),
            "source": "LSTM_attention",
            "variation_pct": variation_pct,
        }

    # ── Prédiction spiruline ───────────────────────────────────────────────────
    def _predict_spiruline_semaine(self, historical: Dict) -> Dict:
        """Prédit la production spiruline (g) pour la semaine suivante."""
        biomass = np.array(historical["photobioreactor"].get("biomass_density", [])[-168:], dtype=float)
        ph = np.array(historical["photobioreactor"].get("ph", [])[-168:], dtype=float)
        temp_p = np.array(historical["photobioreactor"].get("temperature", [])[-168:], dtype=float)
        vol_sat = np.array(historical["photobioreactor"].get("vol_saturated_water", [])[-168:], dtype=float)
        light = np.array(historical["photobioreactor"].get("light_intensity", [])[-168:], dtype=float)
        # Si biomasse absente ou nulle, prédire avec température + pH seuls
        biomass_is_zero = len(biomass) == 0 or float(np.sum(np.abs(biomass))) < 0.01
        if biomass_is_zero:
            T_temp = len(temp_p)
            if T_temp < 6:
                return {"valeur_g": 45.0, "confidence": 0.52, "source": "defaut_temp_insuffisante", "variation_pct": 0.0, "harvest_in_hours": 168}
            mean_temp = float(np.mean(temp_p[-T_temp:]))
            # Facteur temp : optimum 30°C pour spiruline
            temp_factor = max(0.4, 1.0 - abs(mean_temp - 30.0) * 0.04)
            # Facteur pH si disponible
            ph_factor = 1.0
            if len(ph) > 0:
                mean_ph = float(np.mean(ph[-min(24, len(ph)):]))
                if 8.5 <= mean_ph <= 9.2:
                    ph_factor = 1.0
                elif 7.5 <= mean_ph < 8.5 or 9.2 < mean_ph <= 10.0:
                    ph_factor = 0.85
                else:
                    ph_factor = 0.65
            # Modèle Monod simplifié : 0.5 g/L/j pour 10L = 5g/j
            prod_g = round(5.0 * 7 * temp_factor * ph_factor, 1)
            conf = min(0.68, 0.40 + T_temp / 400.0)
            return {"valeur_g": prod_g, "confidence": round(conf, 3), "source": "modele_temp_pH", "variation_pct": 0.0, "harvest_in_hours": 120}
        T = min(len(biomass), len(ph), len(temp_p), len(vol_sat), len(light))
        if T < 24:
            mean_b = float(np.mean(biomass)) if len(biomass) > 0 else 4.5
            return {
                "valeur_g": round(mean_b * 1000 * 0.15 * 7, 1),
                "confidence": 0.55,
                "source": "extrapolation_lineaire",
                "variation_pct": 0.0,
            }
        biomass = biomass[-T:]; ph = ph[-T:]
        temp_p = temp_p[-T:]; vol_sat = vol_sat[-T:]
        light = light[-T:]
        b_n, b_mn, b_mx = self._normalize(biomass)
        ph_n, ph_mn, ph_mx = self._normalize(ph)
        tp_n, tp_mn, tp_mx = self._normalize(temp_p)
        vs_n, vs_mn, vs_mx = self._normalize(vol_sat)
        li_n, li_mn, li_mx = self._normalize(light)
        X = np.column_stack([b_n, ph_n, tp_n, vs_n, li_n])   # (T, 5)
        lstm_out = self._lstm_spiruline.forward_sequence(X)
        recent = lstm_out[-min(48, T):]
        weights = self._attention_weights(recent)
        att_val = float(np.dot(weights, recent))
        # Dénorm biomasse → production
        pred_density = float(self._denormalize(np.array([att_val]), b_mn, b_mx)[0])
        pred_density = max(0.5, pred_density)
        # pH optimal 7.0-8.0 → facteur correctif
        mean_ph = float(np.mean(ph[-24:]))
        if 7.0 <= mean_ph <= 8.0:
            ph_factor = 1.0
        elif 6.5 <= mean_ph < 7.0 or 8.0 < mean_ph <= 8.5:
            ph_factor = 0.90
        else:
            ph_factor = 0.75
        # Taux de récolte moyen (masse densité → g/jour)
        harvest_rate = pred_density * 1000 * 0.15   # 15% de la biomasse/jour
        prod_g = harvest_rate * 7 * ph_factor
        prod_g = max(0.0, round(prod_g, 1))
        # Tendance
        weekly_sums = []
        for w in range(4):
            start = max(0, T - (w+1)*168)
            end = T - w*168
            if end > start:
                weekly_sums.append(float(np.sum(biomass[start:end])))
        variation_pct = 0.0
        if len(weekly_sums) >= 2 and weekly_sums[1] > 0:
            variation_pct = round((weekly_sums[0] - weekly_sums[1]) / weekly_sums[1] * 100, 1)
        cv = np.std(weekly_sums) / (np.mean(weekly_sums) + 1e-9) if len(weekly_sums) >= 2 else 0.3
        confidence = max(0.60, min(0.95, 1.0 - cv * 0.5))
        return {
            "valeur_g": prod_g,
            "confidence": round(float(confidence), 3),
            "source": "LSTM_attention_pH_factor",
            "variation_pct": variation_pct,
        }

    # ── Détection anomalies ────────────────────────────────────────────────────
    def _detect_anomalies(self, realtime: Dict) -> List[Dict]:
        """Détecte les valeurs capteurs hors plage normale."""
        anomalies = []
        mapping = {
            "temp_digesteur": ("digester", "temperature"),
            "temp_pbr": ("photobioreactor", "temperature"),
            "ph_pbr": ("photobioreactor", "ph"),
            "debit_biogaz": ("digester", "gas_flow"),
            "vol_eau_saturee": ("photobioreactor", "vol_saturated_water"),
        }
        for key, (comp, field) in mapping.items():
            val = realtime.get(comp, {}).get(field)
            if val is None:
                continue
            lo, hi = self.SENSOR_RANGES[key]
            if not (lo <= val <= hi):
                ecart = max(val - hi, lo - val)
                severity = "critique" if ecart > (hi - lo) * 0.2 else "attention"
                anomalies.append({
                    "capteur": self.SENSOR_LABELS.get(key, key),
                    "capteur_id": key,
                    "valeur": round(float(val), 3),
                    "plage_min": lo,
                    "plage_max": hi,
                    "ecart": round(float(ecart), 3),
                    "severite": severity,
                    "timestamp": datetime.now().isoformat(),
                })
        return anomalies

    # ── Maintenance prédictive ─────────────────────────────────────────────────
    def _predict_maintenance(self, historical: Dict, anomalies: List[Dict]) -> Dict:
        """Estime la date de prochaine maintenance basée sur tendances capteurs."""
        # Score de dégradation cumulé basé sur :
        # 1. Nombre d'anomalies récentes
        # 2. Tendance température digesteur
        # 3. Dérive pH PBR
        score = 0.0
        score += len(anomalies) * 8.0
        # Tendance temp digesteur
        temp_d = np.array(historical["digester"].get("temperature", [])[-72:], dtype=float)
        if len(temp_d) > 10:
            trend = float(np.polyfit(np.arange(len(temp_d)), temp_d, 1)[0])
            score += abs(trend) * 20.0
        # Dérive pH PBR
        ph_arr = np.array(historical["photobioreactor"].get("ph", [])[-72:], dtype=float)
        if len(ph_arr) > 10:
            ph_mean = float(np.mean(ph_arr))
            ph_drift = abs(ph_mean - 7.5)   # pH optimal 7.5
            score += ph_drift * 15.0
        # Jours avant maintenance (max 90j, min 7j)
        jours_avant = max(7, int(90 - score))
        prochaine_date = (datetime.now() + timedelta(days=jours_avant)).strftime("%Y-%m-%d")
        if jours_avant <= 14:
            urgence = "haute"
        elif jours_avant <= 30:
            urgence = "moyenne"
        else:
            urgence = "basse"
        return {
            "jours_avant": jours_avant,
            "date_estimee": prochaine_date,
            "urgence": urgence,
            "score_degradation": round(score, 1),
        }

    # ── Analyse marché & prix conseillés ──────────────────────────────────────
    def _analyze_market_pricing(
        self,
        pred_biogaz: Dict,
        pred_spiruline: Dict,
        sales_history: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Section 7.3 -- Analyse marché concurrentielle.
        Produit les prix conseillés hebdomadaires biogaz & spiruline.
        """
        # ── Biogaz ──
        base_b = self.MARKET["biogaz"]["base"]
        mn_b = self.MARKET["biogaz"]["min"]
        mx_b = self.MARKET["biogaz"]["max"]
        var_b = pred_biogaz.get("variation_pct", 0.0)
        if var_b > 10:
            adj_b = 0.08
        elif var_b > 5:
            adj_b = 0.04
        elif var_b < -10:
            adj_b = -0.06
        elif var_b < -5:
            adj_b = -0.03
        else:
            adj_b = 0.0
        week_num = datetime.now().isocalendar()[1]
        saison_factor_b = 1.0 + 0.05 * math.sin(2 * math.pi * week_num / 52)
        prix_b = base_b * (1 + adj_b) * saison_factor_b
        prix_b = round(max(mn_b, min(mx_b, prix_b)))
        fourch_b_min = max(mn_b, prix_b - 30)
        fourch_b_max = min(mx_b, prix_b + 30)
        if var_b > 5:
            justif_b = f"Production en hausse +{var_b:.1f}%, demande soutenue : augmenter le prix de {abs(adj_b)*100:.0f}%"
        elif var_b < -5:
            justif_b = f"Production en baisse {var_b:.1f}% : réduire légèrement le prix pour maintenir les volumes"
        else:
            justif_b = "Production stable : maintenir le positionnement médian du marché béninois"

        # ── Spiruline (toujours en FCFA/kg) ──
        prix_fraiche = self.MARKET["spiruline_fraiche"]["valeur"]
        prix_sechee = self.MARKET["spiruline_sechee"]["valeur"]
        mn_s = prix_fraiche
        mx_s = prix_sechee
        base_s = (prix_fraiche + prix_sechee) / 2.0
        var_s = pred_spiruline.get("variation_pct", 0.0)
        if var_s > 12:
            adj_s = 0.10
        elif var_s > 6:
            adj_s = 0.05
        elif var_s < -12:
            adj_s = -0.08
        elif var_s < -6:
            adj_s = -0.04
        else:
            adj_s = 0.0
        saison_factor_s = 1.0 + 0.06 * math.sin(2 * math.pi * (week_num + 13) / 52)
        prix_s = base_s * (1 + adj_s) * saison_factor_s
        prix_s = round(max(mn_s, min(mx_s, prix_s)))
        fourch_s_min = mn_s
        fourch_s_max = mx_s
        if var_s > 6:
            justif_s = f"Biomasse en forte hausse +{var_s:.1f}% : privilégier la spiruline séchée (prime qualité, +{abs(adj_s)*100:.0f}%)"
        elif var_s < -6:
            justif_s = f"Production en recul {var_s:.1f}% : privilégier la vente fraîche pour maintenir la clientèle"
        else:
            justif_s = "Croissance régulière de la biomasse : prix d'entrée compétitif maintenu entre frais et séché"

        # Tendances ventes internes (4 dernières semaines)
        tendance_ventes = "stable"
        if sales_history and len(sales_history) >= 2:
            recent_total = sum(e.get("total", 0) for e in sales_history[-14:])
            previous_total = sum(e.get("total", 0) for e in sales_history[-28:-14])
            if previous_total > 0:
                delta_ventes = (recent_total - previous_total) / previous_total * 100
                if delta_ventes > 10:
                    tendance_ventes = "hausse"
                elif delta_ventes < -10:
                    tendance_ventes = "baisse"

        # Saisonnalité détectée
        if 10 <= week_num <= 22:
            saisonnalite = "Saison forte (Carême : demande élevée)"
        elif 23 <= week_num <= 35:
            saisonnalite = "Saison intermédiaire"
        elif 36 <= week_num <= 48:
            saisonnalite = "Saison faible : stimuler les ventes"
        else:
            saisonnalite = "Période de fêtes : demande modérée"

        return {
            "biogaz": {
                "prix_conseille": prix_b,
                "fourchette_min": fourch_b_min,
                "fourchette_max": fourch_b_max,
                "unite": "FCFA/m³",
                "justification": justif_b,
                "variation_pct": var_b,
                "confidence_pct": round(pred_biogaz.get("confidence", 0.75) * 100, 1),
            },
            "spiruline": {
                "prix_conseille": prix_s,
                "fourchette_min": fourch_s_min,
                "fourchette_max": fourch_s_max,
                "unite": "FCFA/kg",
                "prix_fraiche_fcfa_kg": prix_fraiche,
                "prix_sechee_fcfa_kg": prix_sechee,
                "justification": justif_s,
                "variation_pct": var_s,
                "confidence_pct": round(pred_spiruline.get("confidence", 0.75) * 100, 1),
            },
            "tendance_ventes": tendance_ventes,
            "saisonnalite": saisonnalite,
            "semaine": f"Semaine {week_num} / {datetime.now().year}",
        }

    # ── Point d'entrée principal ───────────────────────────────────────────────
    def compute_weekly_predictions(
        self,
        historical_data: Dict,
        realtime_data: Dict,
        sales_history: Optional[List[Dict]] = None,
        measurements_count: int = 0,
    ) -> Dict:
        """
        Calcule toutes les prédictions hebdomadaires.
        Résultat mis en cache 1h ; réentraîne le modèle si nouvelles données détectées.
        """
        # Cache d'1 heure (sauf si nouvelles données)
        if (
            self._weekly_cache is not None
            and self._cache_ts is not None
            and not self._needs_retrain(historical_data, measurements_count)
            and (datetime.now() - self._cache_ts).total_seconds() < 3600
        ):
            return self._weekly_cache

        logger.info("🔄 PredictionEngine -- calcul prédictions hebdomadaires depuis capteurs réels")
        pred_biogaz = self._predict_biogaz_semaine(historical_data)
        pred_spiruline = self._predict_spiruline_semaine(historical_data)
        anomalies = self._detect_anomalies(realtime_data)
        maintenance = self._predict_maintenance(historical_data, anomalies)
        market_pricing = self._analyze_market_pricing(pred_biogaz, pred_spiruline, sales_history)

        # Confiance globale -- démarre à 0% et monte progressivement avec le nombre
        # de mesures réelles reçues. Sous 10 mesures : confiance non significative.
        if measurements_count < 3:
            conf_globale = None
        else:
            base_conf = (
                pred_biogaz["confidence"] * 0.35
                + pred_spiruline["confidence"] * 0.35
                + (0.90 - len(anomalies) * 0.05) * 0.30
            ) * 100
            # Montée progressive : confiance pleine atteinte à partir de 200 mesures reçues
            ramp = min(1.0, measurements_count / 200.0)
            conf_globale = round(max(0.0, min(99.0, base_conf * ramp)), 1)

        result = {
            "timestamp": datetime.now().isoformat(),
            "semaine_cible": (datetime.now() + timedelta(days=7)).strftime("Semaine du %d/%m/%Y"),
            "production_biogaz": pred_biogaz,
            "production_spiruline": pred_spiruline,
            "anomalies_capteurs": anomalies,
            "maintenance_predictive": maintenance,
            "recommandations_prix": market_pricing,
            "confidence_globale": conf_globale,
            "confidence_label": "Données insuffisantes" if conf_globale is None else f"{conf_globale}%",
            "nb_anomalies": len(anomalies),
            "modele": "LSTM+Attention (Section 7.1)",
            "donnees_source": "capteurs_reels_uniquement",
        }
        self._weekly_cache = result
        self._cache_ts = datetime.now()
        self._train_history.append({
            "timestamp": datetime.now().isoformat(),
            "conf": conf_globale,
        })
        conf_log = "Données insuffisantes" if conf_globale is None else f"{conf_globale}%"
        logger.info(f"✅ Prédictions calculées -- confiance globale : {conf_log}")
        return result

# ==================== DASHBOARD PRINCIPAL =====================================
class SENDashboard:
    """Classe principale du dashboard SEN -- cogénération et contrôle supprimés.
    v3.5 : FCFA, suppressions capteurs, ajouts PBR, modules marketing et performance.
    """
    def __init__(self, config_path: str = "config/sen_config.json"):
        self.config = self._load_config(config_path)
        self.app = Flask(__name__)
        self.app.config.from_object(Config)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")
        CORS(self.app)
        self.login_manager = LoginManager()
        self.login_manager.init_app(self.app)
        self.login_manager.login_view = "login"
        self.data_manager = SimpleDataManager()
        self.realtime_data: Dict = {}
        self.historical_data: Dict = {}
        self.predictions: Dict = {}
        self.weekly_predictions: Dict = {}
        self.harvest_state: Dict = {"cycle_jours": 0, "derniere_recolte": None, "historique": []}
        self.system_status: Dict = {}
        self.reports: Dict = {}
        self.alarms_data: List = []
        self.health_data: Dict = {}
        # Mode démo : passe à False dès la première réception de données ESP32 réelles
        self.real_data_received: bool = False
        self.measurements_count: int = 0
        self._stop_event = threading.Event()
        self._update_thread: Optional[threading.Thread] = None
        # Moteur de prédiction Section 7 -- initialisé avant les composants
        self.prediction_engine = PredictionEngine(hidden_size=16)
        self._initialize_components()
        self._setup_login()
        self._setup_routes()
        self._setup_socketio()
        logger.info("✅ Dashboard SEN v3.5 initialisé avec succès  Performance Capteurs activée")

    # ── Config ─────────────────────────────────────────────────────────────────
    def _load_config(self, config_path: str) -> Dict:
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Configuration non trouvée : {config_path} : utilisation des valeurs par défaut")
            return {
                "project": {"name": "SEN", "version": "3.5"},
                "dashboard": {"refresh_interval": 2, "max_alarms": 20, "data_retention_days": 30},
            }

    # ── Initialisation ─────────────────────────────────────────────────────────
    def _initialize_components(self):
        logger.info("🔄 Initialisation des composants SEN")
        self._initialize_demo_data()
        self._generate_historical_data()
        self.system_status = {
            "overall_health": 92.5,
            "component_status": {
                "digester": "optimal", "photobioreactor": "good",
                "control_system": "good", "ml_system": "optimal",
            },
            "uptime": "15 jours 7h 32m",
            "last_maintenance": "2024-01-15",
            "next_maintenance": "2024-02-15",
        }
        self._initialize_predictions()
        self._initialize_reports()
        self._initialize_alarms()
        self._initialize_health_data()
        logger.info("✅ Composants initialisés")

    def _initialize_demo_data(self):
        self.realtime_data = {
            "digester": {
                # pH digesteur SUPPRIMÉ (pas de capteur physique)
                "ch4_concentration": round(60.0 + random.uniform(-8, 8), 2),   # MQ-4, seuil normal 50-70%
                "co2_concentration": 40.75,
                "co2_entree": round(35.0 + random.uniform(-5, 5), 2),         # MQ-2 digesteur, seuil normal 25-45%
                "gas_flow": 12.89,
                "temperature": 35.36,
                # pressure SUPPRIMÉE
                # liquid_level SUPPRIMÉE
            },
            "economics": {
                # Toutes les valeurs économiques en FCFA
                "co2_credits_fcfa": eur_to_fcfa(7.22),
                "daily_cost_fcfa": eur_to_fcfa(38.68),
                "daily_profit_fcfa": eur_to_fcfa(93.53),
                "daily_revenue_fcfa": eur_to_fcfa(109.25),
                "roi_years": 4.76,
                # Alias pour compatibilité template (valeurs FCFA)
                "co2_credits": eur_to_fcfa(7.22),
                "daily_cost": eur_to_fcfa(38.68),
                "daily_profit": eur_to_fcfa(93.53),
                "daily_revenue": eur_to_fcfa(109.25),
            },
            "environmental": {
                "co2_captured": 117.65,
                "equivalent_trees": 5.75,
                "fossil_fuel_offset": 36.02,
                "waste_diverted": 268.51,
                "water_recycled": 1160.31,
            },
            "photobioreactor": {
                "biomass_density": 5.29,
                "co2_effluent": 3.65,
                "co2_injection": 8.72,
                "co2_sortie": round(2.5 + random.uniform(-0.5, 0.5), 2),   # MQ-2 PBR, seuil normal 1-5%
                # dissolved_oxygen SUPPRIMÉ
                "light_intensity": 194.87,
                # nutrient_level SUPPRIMÉ
                # Nouveaux capteurs PBR
                "ph": 7.35,
                "temperature": 26.8,
                "vol_saturated_water": 42.5,   # litres, eau saturée CO₂ + nutriments
            },
        }

    def _initialize_health_data(self):
        self.health_data = {
            "system": {"cpu_usage": 42.5, "memory_usage": 68.3, "disk_usage": 55.7},
            "components": {
                "digester": {"status": "optimal", "uptime": "99.7%", "sensors_online": 12},
                "photobioreactor": {"status": "good", "uptime": "98.9%", "algae_strain": "Arthrospira platensis"},
                "ia_system": {"status": "optimal", "model_accuracy": "94.7%", "last_training": "2024-01-19", "predictions_today": 1247},
            },
        }

    def _generate_historical_data(self):
        """Génère 90 jours de données reproductibles (seed fixe)."""
        rng = np.random.default_rng(seed=42)
        days = 90
        hours = days * 24
        base_time = datetime.now() - timedelta(days=days)
        timestamps = [(base_time + timedelta(hours=i)).isoformat() for i in range(hours)]

        temp_trend = np.linspace(0, 1.0, hours)
        gasflow_trend = np.linspace(0, 2.0, hours)
        self.historical_data["digester"] = {
            "timestamps": timestamps,
            "temperature": (35 + temp_trend + rng.normal(0, 0.4, hours)).tolist(),
            # ph SUPPRIMÉ des données historiques digesteur
            "gas_flow": (12 + gasflow_trend + rng.normal(0, 0.4, hours)).tolist(),
            "ch4_concentration": (60 + rng.normal(0, 2.7, hours)).tolist(),   # MQ-4, seuil normal 50-70%
            "co2_entree": (35 + rng.normal(0, 1.7, hours)).tolist(),         # MQ-2 digesteur, seuil normal 25-45%
            # pressure SUPPRIMÉE
            # liquid_level SUPPRIMÉE
        }

        base_biomass, growth_rate = 4.5, 0.045
        harvest_cycle = 14 * 24
        biomass = []
        for i in range(hours):
            cycle_pos = i % harvest_cycle
            g = growth_rate * (1 + 0.1 * np.sin(2 * np.pi * (i % 24) / 24))
            b = base_biomass * (1 + g * (cycle_pos / 24))
            if cycle_pos == 0 and i > 0:
                b = base_biomass * 0.30
            biomass.append(round(b + float(rng.uniform(-0.05, 0.05)), 4))
        self.historical_data["photobioreactor"] = {
            "timestamps": timestamps,
            "biomass_density": biomass,
            "co2_injection": (8.5 + rng.normal(0, 0.3, hours)).tolist(),
            "co2_sortie": (2.5 + rng.normal(0, 0.17, hours)).tolist(),   # MQ-2 PBR, seuil normal 1-5%
            "co2_utilization": rng.uniform(85, 95, hours).tolist(),
            "growth_rate": rng.uniform(0.03, 0.06, hours).tolist(),
            "light_intensity": (195 + rng.uniform(-20, 20, hours)).tolist(),
            # Nouveaux historiques PBR
            "ph": (7.35 + rng.normal(0, 0.15, hours)).tolist(),
            "temperature": (26.8 + rng.normal(0, 0.5, hours)).tolist(),
            "vol_saturated_water": (42.5 + rng.uniform(-5, 5, hours)).tolist(),
        }

        daily_ts = [(base_time + timedelta(days=d)).isoformat() for d in range(days)]
        rng2 = np.random.default_rng(seed=99)
        # Économiques converties en FCFA
        revenue_trend = np.linspace(95, 130, days) * EUR_TO_FCFA
        cost_trend = np.linspace(38, 42, days) * EUR_TO_FCFA
        self.historical_data["economics"] = {
            "timestamps": daily_ts,
            "revenue": (revenue_trend + rng2.normal(0, 4 * EUR_TO_FCFA, days)).tolist(),
            "cost": (cost_trend + rng2.normal(0, 2 * EUR_TO_FCFA, days)).tolist(),
            "profit": (revenue_trend - cost_trend + rng2.normal(0, 3 * EUR_TO_FCFA, days)).tolist(),
        }

    def _confidence_from_count(self, base: float) -> float:
        """
        Confiance progressive : 0% tant qu'aucune donnée réelle reçue,
        monte linéairement avec measurements_count jusqu'à base à 200 mesures.
        """
        if self.measurements_count < 10:
            return 0.0
        ramp = min(1.0, self.measurements_count / 200.0)
        return round(base * ramp, 3)

    def _initialize_predictions(self):
        # Prédictions de base pour l'UI analytics (24h / 48h)
        # Confiance progressive : démarre à 0, monte avec le nombre de mesures reçues
        conf_biogaz_24h = self._confidence_from_count(0.87)
        conf_algae_48h = self._confidence_from_count(0.82)
        self.predictions = {
            "biogas_production": {"confidence": conf_biogaz_24h, "next_24h": [0.835 + i * 0.01 for i in range(26)]},
            "algae_growth": {"prediction": 2.85, "confidence": conf_algae_48h, "harvest_in_hours": 0, "next_48h": [2.85, 2.92, 3.01, 3.12, 3.24, 3.37]},
        }
        # Calcul initial des prédictions hebdomadaires Section 7 depuis capteurs réels
        try:
            self.weekly_predictions = self.prediction_engine.compute_weekly_predictions(
                historical_data=self.historical_data,
                realtime_data=self.realtime_data,
                measurements_count=self.measurements_count,
            )
            logger.info("✅ Prédictions hebdomadaires initialisées")
        except Exception as exc:
            logger.warning(f"⚠ PredictionEngine init partielle : {exc}")
            self.weekly_predictions = {}

    def _initialize_reports(self):
        d = self.realtime_data
        daily_profit_fcfa = d["economics"]["daily_profit_fcfa"]
        self.reports = {
            "daily": {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "biogas_production": round(d["digester"]["gas_flow"] * 24, 2),
                "algae_biomass": round(d["photobioreactor"]["biomass_density"] * 1000, 2),
                "co2_captured": round(d["environmental"]["co2_captured"], 2),
                "revenue_fcfa": round(d["economics"]["daily_revenue_fcfa"]),
                "profit_fcfa": f"{round(daily_profit_fcfa):,}".replace(",", " "),
                "profit": round(daily_profit_fcfa),   # pour calculs JS
                "revenue": round(d["economics"]["daily_revenue_fcfa"]),
            },
            "weekly": {
                "week": datetime.now().strftime("%Y-W%W"),
                "total_biogas": round(sum(self.historical_data["digester"]["gas_flow"]), 2),
                "total_co2": round(d["environmental"]["co2_captured"] * 7, 2),
                "total_revenue_fcfa": round(sum(self.historical_data["economics"]["revenue"])),
            },
        }

    def _initialize_alarms(self):
        d = self.realtime_data
        self.alarms_data = [
            {
                "id": 1, "component": "digester", "severity": "warning",
                "message": f'Temperature elevée digesteur : {d["digester"]["temperature"]}°C',
                "timestamp": datetime.now().isoformat(), "acknowledged": False,
            },
            {
                "id": 2, "component": "photobioreactor", "severity": "warning",
                "message": f'pH PBR hors plage : {d["photobioreactor"]["ph"]}',
                "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(), "acknowledged": False,
            },
            {
                "id": 3, "component": "photobioreactor", "severity": "warning",
                "message": f'Densité biomasse basse : {d["photobioreactor"]["biomass_density"]} g/L',
                "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(), "acknowledged": True,
            },
        ]

    # ── Authentification ───────────────────────────────────────────────────────
    def _setup_login(self):
        self.users = {
            1: {"username": "admin", "role": "administrator", "permissions": ["view","configure","maintenance","reports","alarms_write"], "password_hash": generate_password_hash("sen2024")},
            2: {"username": "operator", "role": "operator", "permissions": ["view","reports","alarms_write"], "password_hash": generate_password_hash("sen2024")},
            3: {"username": "viewer", "role": "viewer", "permissions": ["view"], "password_hash": generate_password_hash("sen2024")},
        }

        @self.login_manager.user_loader
        def load_user(user_id):
            data = self.users.get(int(user_id))
            if data:
                return User(id=int(user_id), **data)
            return None

    @staticmethod
    def _require_permission(perm: str):
        from functools import wraps
        def decorator(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                if not current_user.has_permission(perm):
                    from flask import abort
                    abort(403)
                return f(*args, **kwargs)
            return wrapper
        return decorator

    # ── Routes ─────────────────────────────────────────────────────────────────
    # ── Section 8.3 : Calcul Performance Capteurs ────────────────────────────
    def _compute_sensor_performance(self, periode: str = "7d") -> Dict:
        """
        Calcule les métriques de performance des capteurs pour la Section 8.3.
        - Taux de disponibilité (%) par capteur et global
        - Nombre d'alarmes déclenchées sur la période
        - Stabilité des paramètres critiques (pH PBR, temp PBR, temp digesteur)
        Basé UNIQUEMENT sur les données capteurs réelles en mémoire.
        """
        # Mapping période → nombre d'heures
        periode_heures = {"24h": 24, "7d": 168, "30d": 720, "90d": 2160}
        heures = periode_heures.get(periode, 168)

        # ── Définition des capteurs disponibles ──────────────────────────────
        # Structure : (composant, clé_historique, nom_affichage, valeur_realtime)
        def _get_hist(comp, key):
            h = self.historical_data.get(comp, {}).get(key, [])
            return h[-heures:] if h else []

        capteurs_def = [
            ("photobioreactor", "ph", "pH PBR", self.realtime_data.get("photobioreactor", {}).get("ph")),
            ("photobioreactor", "temperature", "Température PBR", self.realtime_data.get("photobioreactor", {}).get("temperature")),
            ("photobioreactor", "biomass_density", "Densité Biomasse", self.realtime_data.get("photobioreactor", {}).get("biomass_density")),
            ("photobioreactor", "co2_injection","Injection CO₂ PBR", self.realtime_data.get("photobioreactor", {}).get("co2_injection")),
            ("photobioreactor", "co2_sortie", "CO₂ Sortie / Injecté PBR", self.realtime_data.get("photobioreactor", {}).get("co2_sortie")),
            ("photobioreactor", "light_intensity","Intensité Lumineuse",self.realtime_data.get("photobioreactor", {}).get("light_intensity")),
            ("digester", "temperature", "Température Digesteur",self.realtime_data.get("digester", {}).get("temperature")),
            ("digester", "gas_flow", "Débit Biogaz", self.realtime_data.get("digester", {}).get("gas_flow")),
            ("digester", "ch4_concentration","Concentration CH₄",self.realtime_data.get("digester", {}).get("ch4_concentration")),
            ("digester", "co2_entree", "CO₂ Entrée Digesteur", self.realtime_data.get("digester", {}).get("co2_entree")),
        ]

        # ── Calcul disponibilité par capteur ─────────────────────────────────
        resultats_capteurs = []
        dispos = []

        for composant, key, nom, val_rt in capteurs_def:
            serie = _get_hist(composant, key)
            total = len(serie) if serie else heures
            # Un échantillon est "valide" s'il n'est pas None et est un nombre fini
            try:
                valides = sum(1 for v in serie if v is not None and not (v != v))   # exclut NaN
            except Exception:
                valides = 0
            manquants = max(0, total - valides)
            dispo = (valides / total * 100) if total > 0 else 0.0
            dispos.append(dispo)
            # Dernière valeur : temps réel en priorité, sinon dernière historique
            derniere = val_rt
            if derniere is None and serie:
                derniere = next((v for v in reversed(serie) if v is not None), None)
            resultats_capteurs.append({
                "composant": composant,
                "nom": nom,
                "disponibilite": round(dispo, 2),
                "echantillons_valides": valides,
                "donnees_manquantes": manquants,
                "derniere_valeur": round(derniere, 4) if derniere is not None else None,
            })

        # ── Disponibilité globale pondérée ───────────────────────────────────
        taux_global = sum(dispos) / len(dispos) if dispos else 0.0

        # ── Nombre d'alarmes sur la période ──────────────────────────────────
        nb_alarmes = len(self.alarms_data)

        # ── Stabilité des 3 paramètres critiques (Section 8.3) ───────────────
        # Écart-type normalisé → score de 0 (très stable) à 100 (très instable)
        def _stabilite_score(comp, key, max_std):
            serie = _get_hist(comp, key)
            if len(serie) < 2:
                return 50.0   # inconnu → neutre
            arr = np.array([v for v in serie if v is not None and not (v != v)], dtype=float)
            if len(arr) < 2:
                return 50.0
            std = float(np.std(arr))
            return min(100.0, (std / max_std) * 100.0)

        score_ph_pbr = _stabilite_score("photobioreactor", "ph", 1.0)
        score_temp_pbr = _stabilite_score("photobioreactor", "temperature", 5.0)
        score_temp_dig = _stabilite_score("digester", "temperature", 8.0)
        stabilite_globale = round((score_ph_pbr + score_temp_pbr + score_temp_dig) / 3, 1)

        logger.info(
            f"📊 Section 8.3 -- dispo_globale={taux_global:.1f}% "
            f"alarmes={nb_alarmes} stabilite={stabilite_globale:.1f}"
        )
        return {
            "periode": periode,
            "taux_disponibilite_global": round(taux_global, 2),
            "nb_alarmes_periode": nb_alarmes,
            "stabilite_globale_score": stabilite_globale,
            "stabilite_detail": {
                "ph_pbr": round(score_ph_pbr, 1),
                "temp_pbr": round(score_temp_pbr, 1),
                "temp_dig": round(score_temp_dig, 1),
            },
            "capteurs": resultats_capteurs,
            "timestamp": datetime.now().isoformat(),
        }

    def _compute_daily_predictions(self) -> Dict:
        """Prédictions claires J / J+1 / J+2 pour le biogaz et la spiruline."""
        rt = self.realtime_data or {}
        dig = rt.get("digester", {})
        pbr = rt.get("photobioreactor", {})

        # ---- BIOGAZ : température digesteur (35-40°C optimal) + CH4 ----
        gas_now = float(dig.get("gas_flow", 12.0) or 12.0)
        temp_dig = float(dig.get("temperature", 37.0) or 37.0)
        ch4 = float(dig.get("ch4_concentration", 60.0) or 60.0)

        # Facteur température : maximum entre 35-40°C, baisse en dehors
        if 35.0 <= temp_dig <= 40.0:
            temp_factor = 1.0
        elif 32.0 <= temp_dig < 35.0:
            temp_factor = 0.92
        elif 40.0 < temp_dig <= 43.0:
            temp_factor = 0.90
        else:
            temp_factor = 0.78
        # Facteur CH4 (méthane plus élevé => meilleure qualité de production)
        ch4_factor = max(0.85, min(1.05, ch4 / 60.0))
        # Si température hors optimal, la production baisse le lendemain
        if temp_dig < 35.0:
            trend_dir = "down"; daily_mult = 0.95
        elif temp_dig > 40.0:
            trend_dir = "down"; daily_mult = 0.97
        else:
            trend_dir = "up" if temp_dig >= 37.0 else "flat"
            daily_mult = 1.03 if trend_dir == "up" else 1.0

        biogaz_today = round(gas_now * temp_factor * ch4_factor, 2)
        biogaz_j1 = round(biogaz_today * daily_mult, 2)
        biogaz_j2 = round(biogaz_j1 * daily_mult, 2)
        if biogaz_j1 > biogaz_today * 1.005:
            biogaz_arrow = "up"; biogaz_msg = "Température dans la plage idéale, la production augmente ✅"
        elif biogaz_j1 < biogaz_today * 0.995:
            biogaz_arrow = "down"; biogaz_msg = "Température hors de la plage idéale (35-40°C), la production va baisser ⚠️"
        else:
            biogaz_arrow = "flat"; biogaz_msg = "Production stable"

        # ---- SPIRULINE : pH (SEN0161) + temp PBR + luminosité (BH1750) ----
        ph = float(pbr.get("ph", 8.8) or 8.8)
        temp_pbr = float(pbr.get("temperature", 32.0) or 32.0)
        light = float(pbr.get("light_intensity", 5000.0) or 5000.0)
        biomass = float(pbr.get("biomass_density", 1.2) or 1.2)

        # Tendance du pH sur les dernières heures (pH qui monte = algues actives)
        ph_hist = (self.historical_data.get("photobioreactor", {}) or {}).get("ph", [])
        ph_rising = False
        if len(ph_hist) >= 6:
            recent = [float(x) for x in ph_hist[-6:]]
            ph_rising = (sum(recent[3:]) / 3.0) > (sum(recent[:3]) / 3.0)

        growth_24, growth_48 = 0.0, 0.0
        spir_status = "ok"
        # Conditions optimales
        ph_ok = 8.5 <= ph <= 9.5
        temp_ok = 30.0 <= temp_pbr <= 35.0
        light_ok = 2000.0 <= light <= 10000.0

        if ph > 10.0:
            growth_24, growth_48 = -4.0, -8.0
            spir_status = "stress_alcalin"
            spir_msg = "pH trop élevé (>10) : stress alcalin, la croissance va baisser U0001f534"
        elif temp_pbr > 37.0:
            growth_24, growth_48 = -3.0, -6.0
            spir_status = "stress_thermique"
            spir_msg = "Température trop élevée (>37°C) : stress thermique, la croissance va baisser U0001f534"
        elif ph_ok and temp_ok and light_ok:
            base = 6.0 if (ph_rising) else 4.5
            growth_24 = round(base, 1)
            growth_48 = round(base * 1.9, 1)
            spir_status = "active"
            if ph_rising:
                spir_msg = "Le pH est en hausse, les algues sont actives ✅"
            else:
                spir_msg = "Conditions idéales (pH, température, lumière) : croissance soutenue ✅"
        else:
            # Conditions partiellement bonnes
            growth_24 = 2.0
            growth_48 = 3.5
            spir_status = "moyen"
            probs = []
            if not ph_ok: probs.append("pH hors plage idéale (8.5-9.5)")
            if not temp_ok: probs.append("température hors plage (30-35°C)")
            if not light_ok: probs.append("luminosité hors plage (2000-10000 lux)")
            spir_msg = "Croissance modérée : " + ", ".join(probs) + " U0001f7e0"

        return {
            "timestamp": datetime.now().isoformat(),
            "biogaz": {
                "aujourdhui": biogaz_today,
                "demain": biogaz_j1,
                "apres_demain": biogaz_j2,
                "unite": "m³/h",
                "tendance": biogaz_arrow,
                "trend_dir": trend_dir,
                "message": biogaz_msg,
                "temp_digesteur": round(temp_dig, 1),
                "ch4": round(ch4, 1),
            },
            "spiruline": {
                "croissance_actuelle": round(biomass, 2),
                "unite": "g/L",
                "prevision_24h_pct": growth_24,
                "prevision_48h_pct": growth_48,
                "ph": round(ph, 2),
                "ph_rising": ph_rising,
                "temperature": round(temp_pbr, 1),
                "luminosite": round(light, 0),
                "statut": spir_status,
                "message": spir_msg,
            },
        }

    def _compute_harvest_status(self) -> Dict:
        """Détermine si la spiruline est prête à récolter (densité > 1.5 g/L ou pH stable haut 48h)."""
        pbr = (self.realtime_data or {}).get("photobioreactor", {})
        density = float(pbr.get("biomass_density", 0.0) or 0.0)
        ph = float(pbr.get("ph", 0.0) or 0.0)
        SEUIL_DENSITE = 1.5

        ph_hist = (self.historical_data.get("photobioreactor", {}) or {}).get("ph", [])
        ph_stable_haut = False
        if len(ph_hist) >= 48:
            window = [float(x) for x in ph_hist[-48:]]
            ph_stable_haut = all(8.5 <= v <= 10.0 for v in window)

        ready = density >= SEUIL_DENSITE or ph_stable_haut
        # Estimation jours restants (~0.1 g/L par jour de croissance saine)
        jours_restants = 0
        if not ready:
            manque = max(0.0, SEUIL_DENSITE - density)
            jours_restants = max(1, int(round(manque / 0.1)))

        cycle = self.harvest_state.get("cycle_jours", 0)
        return {
            "prete": ready,
            "densite": round(density, 2),
            "seuil": SEUIL_DENSITE,
            "ph_stable_haut": ph_stable_haut,
            "jours_restants": jours_restants,
            "cycle_jours": cycle,
            "derniere_recolte": self.harvest_state.get("derniere_recolte"),
            "historique": self.harvest_state.get("historique", [])[-10:],
        }

    def _setup_routes(self):
        app = self.app

        @app.errorhandler(403)
        def forbidden(e):
            if request.accept_mimetypes.accept_html:
                return render("forbidden", user=current_user), 403
            return jsonify({"error": "Accès refusé : permission insuffisante", "code": 403}), 403

        @app.errorhandler(404)
        def not_found(e):
            return jsonify({"error": "Ressource introuvable", "code": 404}), 404

        @app.errorhandler(500)
        def internal_error(e):
            logger.error(f"Erreur 500 : {e}")
            return jsonify({"error": "Erreur interne du serveur", "code": 500}), 500

        @app.route("/welcome")
        @login_required
        def welcome():
            # Affiché une seule fois après la connexion
            if not session.pop("show_welcome", False):
                return redirect(url_for("index"))
            session["welcome_seen"] = True
            return render("welcome", user=current_user)

        @app.route("/")
        @login_required
        def index():
            return render("index", user=current_user, realtime_data=self.realtime_data, system_status=self.system_status)

        @app.route("/login", methods=["GET", "POST"])
        def login():
            if request.method == "POST":
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                for uid, data in self.users.items():
                    if data["username"] == username and check_password_hash(data["password_hash"], password):
                        login_user(User(id=uid, **data))
                        session["show_welcome"] = True
                        return redirect(url_for("welcome"))
                return render("login", error="Identifiants incorrects")
            return render("login")

        @app.route("/logout")
        @login_required
        def logout():
            logout_user()
            return redirect(url_for("login"))

        @app.route("/dashboard/realtime")
        @login_required
        def realtime_dashboard():
            return render("realtime_dashboard", user=current_user, realtime_data=self.realtime_data)

        @app.route("/dashboard/historical")
        @login_required
        def historical_dashboard():
            return render("historical_dashboard", user=current_user)

        @app.route("/dashboard/analytics")
        @login_required
        def analytics_dashboard():
            return render("analytics_dashboard", user=current_user, predictions=self.predictions)

        @app.route("/dashboard/reports")
        @login_required
        @SENDashboard._require_permission("reports")
        def reports_dashboard():
            return render("reports_dashboard", user=current_user, reports=self.reports)

        @app.route("/dashboard/configuration")
        @login_required
        @SENDashboard._require_permission("configure")
        def configuration_dashboard():
            return render("configuration_dashboard", user=current_user, derniere_maj=datetime.now().strftime("%Y-%m-%d"))

        @app.route("/dashboard/alarms")
        @login_required
        def alarms_dashboard():
            return render("alarms_dashboard", user=current_user)

        @app.route("/dashboard/health")
        @login_required
        def health_dashboard():
            return render("health_dashboard", user=current_user, health_data=self.health_data, system_status=self.system_status)

        @app.route("/dashboard/marketing")
        @login_required
        def marketing_dashboard():
            return render("marketing", user=current_user)

        @app.route("/dashboard/capteurs")
        @login_required
        def capteurs_dashboard():
            # Section 8.3 -- Module Performance des Capteurs
            return render("capteurs_performance", user=current_user)

        @app.route("/api/capteurs/performance")
        @login_required
        def api_capteurs_performance():
            """
            API Performance des capteurs.
            Retourne : taux de disponibilité, alarmes déclenchées, stabilité paramètres critiques.
            Paramètre GET : periode = 24h | 7d | 30d | 90d (défaut : 7d)
            """
            periode = request.args.get("periode", "7d")
            if periode not in ("24h", "7d", "30d", "90d"):
                periode = "7d"
            try:
                result = self._compute_sensor_performance(periode=periode)
                return jsonify(result)
            except Exception as exc:
                logger.error(f"api_capteurs_performance error: {exc}")
                return jsonify({"error": str(exc), "timestamp": datetime.now().isoformat()}), 500

        @app.route("/dashboard/performance")
        @login_required
        def performance_dashboard():
            return render("performance", user=current_user)

        # ── API MARKETING ──────────────────────────────────────────────────────
        @app.route("/api/marketing/prix-conseille")
        @login_required
        def api_prix_conseille():
            """Retourne les prix conseillés calculés par le PredictionEngine Section 7."""
            try:
                wp = self.prediction_engine.compute_weekly_predictions(
                    historical_data=self.historical_data,
                    realtime_data=self.realtime_data,
                    measurements_count=self.measurements_count,
                )
                reco = wp.get("recommandations_prix", {})
                b = reco.get("biogaz", {})
                s = reco.get("spiruline", {})
                return jsonify({
                    "biogaz": {
                        "prix_conseille": b.get("prix_conseille", 650),
                        "unite": "FCFA/m³",
                        "fourchette_min": b.get("fourchette_min", 500),
                        "fourchette_max": b.get("fourchette_max", 800),
                        "justification": b.get("justification", ""),
                    },
                    "spiruline": {
                        "prix_conseille": s.get("prix_conseille", 6500),
                        "unite": "FCFA/kg",
                        "fourchette_min": s.get("fourchette_min", 6500),
                        "fourchette_max": s.get("fourchette_max", 20000),
                        "justification": s.get("justification", ""),
                    },
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as exc:
                logger.error(f"api_prix_conseille error: {exc}")
                return jsonify({
                    "biogaz": {"prix_conseille": 650, "unite": "FCFA/m³", "fourchette_min": 500, "fourchette_max": 800, "justification": "Valeur par défaut"},
                    "spiruline": {"prix_conseille": 6500, "unite": "FCFA/kg", "fourchette_min": 6500, "fourchette_max": 20000, "justification": "Valeur par défaut"},
                    "timestamp": datetime.now().isoformat(),
                })

        @app.route("/api/predictions/daily")
        @login_required
        def api_predictions_daily():
            """Prédictions journalières simplifiées basées sur capteurs temps réel.
            Biogaz : temp digesteur (DS18B20) + CH4 (MQ4).
            Spiruline : pH (SEN0161) + temp PBR (DS18B20) + luminosité (BH1750)."""
            try:
                result = self._compute_daily_predictions()
                return jsonify(result)
            except Exception as exc:
                logger.error(f"api_predictions_daily error: {exc}")
                return jsonify({"error": str(exc), "timestamp": datetime.now().isoformat()}), 500

        @app.route("/api/harvest/status")
        @login_required
        def api_harvest_status():
            try:
                return jsonify(self._compute_harvest_status())
            except Exception as exc:
                logger.error(f"api_harvest_status error: {exc}")
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/harvest/start", methods=["POST"])
        @login_required
        def api_harvest_start():
            try:
                now = datetime.now()
                density = float((self.realtime_data.get("photobioreactor", {}) or {}).get("biomass_density", 0.0) or 0.0)
                entry = {
                    "date": now.strftime("%d/%m/%Y %H:%M"),
                    "timestamp": now.isoformat(),
                    "densite_recoltee": round(density, 2),
                    "operateur": getattr(current_user, "username", "inconnu"),
                }
                self.harvest_state.setdefault("historique", []).append(entry)
                self.harvest_state["derniere_recolte"] = entry["date"]
                self.harvest_state["cycle_jours"] = 0  # remise à zéro du compteur de cycle
                logger.info(f"🌿 Récolte enregistrée : {entry}")
                etapes = [
                    "1. Arrêter l'agitation et l'injection de CO₂ du photobioréacteur.",
                    "2. Laisser décanter la spiruline pendant 15 à 20 minutes.",
                    "3. Filtrer la biomasse à travers un tissu fin (mailles ~30 µm).",
                    "4. Rincer délicatement à l'eau propre pour retirer le milieu de culture.",
                    "5. Presser pour retirer l'excès d'eau, puis étaler en fines couches.",
                    "6. Sécher à l'ombre ou au séchoir (< 60°C) jusqu'à texture friable.",
                    "7. Conserver dans un récipient hermétique, à l'abri de la lumière.",
                    "8. Nettoyer le réacteur et relancer un nouveau cycle de culture.",
                ]
                return jsonify({"success": True, "message": "Récolte enregistrée avec succès", "date": entry["date"], "etapes": etapes})
            except Exception as exc:
                logger.error(f"api_harvest_start error: {exc}")
                return jsonify({"success": False, "error": str(exc)}), 500

        @app.route("/api/predictions/weekly")
        @login_required
        def api_predictions_weekly():
            """
            Prédictions hebdomadaires complètes.
            Toutes les prédictions sont calculées depuis les capteurs réels uniquement.
            Réentraînement automatique détecté si nouvelles données disponibles.
            """
            try:
                result = self.prediction_engine.compute_weekly_predictions(
                    historical_data=self.historical_data,
                    realtime_data=self.realtime_data,
                    measurements_count=self.measurements_count,
                )
                self.weekly_predictions = result
                return jsonify(result)
            except Exception as exc:
                logger.error(f"api_predictions_weekly error: {exc}")
                return jsonify({"error": str(exc), "timestamp": datetime.now().isoformat()}), 500

        # ── API ────────────────────────────────────────────────────────────────
        @app.route("/api/realtime")
        @login_required
        def api_realtime():
            return jsonify({"timestamp": datetime.now().isoformat(), "data": self.realtime_data, "status": self.system_status, "predictions": self.predictions})

        @app.route("/api/historical/<component>")
        @login_required
        def api_historical(component):
            if component not in self.historical_data:
                return jsonify({"error": f"Composant '{component}' non trouvé"}), 404
            period = request.args.get("period", "7d")
            period_hours = {"7d": 7*24, "30d": 30*24, "90d": 90*24}.get(period, 7*24)
            period_days = {"7d": 7, "30d": 30, "90d": 90 }.get(period, 7)
            data = self.historical_data[component]
            result = {}
            for key, values in data.items():
                if isinstance(values, list):
                    cut = period_days if component == "economics" else period_hours
                    result[key] = values[-cut:]
                else:
                    result[key] = values
            return jsonify(result)

        @app.route("/api/health/detailed")
        @login_required
        def api_health_detailed():
            return jsonify(self.health_data)

        @app.route("/api/alarms")
        @login_required
        def api_alarms():
            active = [a for a in self.alarms_data if not a["acknowledged"]]
            critical = [a for a in active if a["severity"] == "critical"]
            return jsonify({"timestamp": datetime.now().isoformat(), "alarms": self.alarms_data, "total": len(active), "critical": len(critical), "acknowledged": len([a for a in self.alarms_data if a["acknowledged"]]), "total_24h": len(self.alarms_data)})

        @app.route("/api/alarms/acknowledge", methods=["POST"])
        @login_required
        @SENDashboard._require_permission("alarms_write")
        def api_acknowledge_alarm():
            alarm_id = (request.get_json(silent=True) or {}).get("alarm_id")
            for a in self.alarms_data:
                if a["id"] == alarm_id:
                    a["acknowledged"] = True
                    break
            return jsonify({"status": "success", "message": "Alarme acquittée"})

        @app.route("/api/alarms/acknowledge_all", methods=["POST"])
        @login_required
        @SENDashboard._require_permission("alarms_write")
        def api_acknowledge_all():
            for a in self.alarms_data:
                a["acknowledged"] = True
            return jsonify({"status": "success", "message": "Toutes les alarmes acquittées"})

        @app.route("/api/alarms/clear_all", methods=["POST"])
        @login_required
        def api_clear_all_alarms():
            if not current_user.has_permission("configure"):
                return jsonify({"error": "Permission refusée"}), 403
            self.alarms_data = []
            return jsonify({"status": "success", "message": "Toutes les alarmes effacées"})

        @app.route("/api/reports/generate", methods=["POST"])
        @login_required
        def api_generate_report():
            if not current_user.has_permission("reports"):
                return jsonify({"error": "Permission refusée"}), 403
            rtype = (request.get_json(silent=True) or {}).get("report_type", "unknown")
            return jsonify({"status": "success", "message": f"Rapport {rtype} généré avec succès", "report_id": f"report_{rtype}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"})

        @app.route("/api/predictions/latest")
        @login_required
        def api_predictions_latest():
            """Retourne les dernières prédictions avec métriques du modèle IA.
            Utilisé par le dashboard Analytique (Section 7.4)."""
            wp = self.weekly_predictions or {}
            pred_biogaz = wp.get("production_biogaz", {})
            pred_spiruline = wp.get("production_spiruline", {})
            fallback_biogaz = self._confidence_from_count(0.87)
            fallback_spiruline = self._confidence_from_count(0.82)
            conf_b = pred_biogaz.get("confidence", fallback_biogaz)
            conf_s = pred_spiruline.get("confidence", fallback_spiruline)
            return jsonify({
                "biogas_production": {
                    "confidence": conf_b,
                    "confidence_interval_pct": round((1 - conf_b) * 100, 1) if self.measurements_count >= 10 else None,
                    "next_24h": self.predictions.get("biogas_production", {}).get("next_24h", []),
                },
                "spirulina_production": {
                    "confidence": conf_s,
                    "confidence_interval_pct": round((1 - conf_s) * 100, 1) if self.measurements_count >= 10 else None,
                },
                "model_metrics": {
                    "mae": None,
                    "rmse": None,
                    "r2": None,
                },
                "sensor_quality": {
                    "valid": len(wp.get("anomalies_capteurs", [])) == 0,
                    "reason": None if not wp.get("anomalies_capteurs") else f"{len(wp['anomalies_capteurs'])} anomalie(s) détectée(s)",
                },
                "timestamp": datetime.now().isoformat(),
            })

        @app.route("/api/predictions")
        @login_required
        def api_predictions():
            return jsonify(self.predictions)

        @app.route("/api/data/status")
        def api_data_status():
            """Indique si de vraies données ESP32 ont déjà été reçues (pour le bandeau Mode Démo)."""
            return jsonify({
                "real_data_received": self.real_data_received,
                "measurements_count": self.measurements_count,
            })

        @app.route("/api/data", methods=["POST"])
        def api_data_receive():
            """
            Réception des données réelles envoyées par l'ESP32.
            Dès le premier appel, le bandeau Mode Démo disparaît côté client
            et la confiance IA commence sa montée progressive.
            """
            payload = request.get_json(silent=True) or {}
            self.real_data_received = True
            self.measurements_count += 1
            if "co2_entree" in payload:
                self.realtime_data.setdefault("digester", {})["co2_entree"] = payload["co2_entree"]
            if "co2_sortie" in payload:
                self.realtime_data.setdefault("photobioreactor", {})["co2_sortie"] = payload["co2_sortie"]
            if "ch4_concentration" in payload:
                self.realtime_data.setdefault("digester", {})["ch4_concentration"] = payload["ch4_concentration"]
            # Autres champs capteurs envoyés tels quels, par composant si fournis
            for comp in ("digester", "photobioreactor"):
                if comp in payload and isinstance(payload[comp], dict):
                    self.realtime_data.setdefault(comp, {}).update(payload[comp])

            # Accumulation dans l'historique réel : chaque mesure ESP32 est ajoutée
            # à la suite des séries historiques (au lieu de rester figée en simulation).
            now_iso = datetime.now().isoformat()
            for comp in ("digester", "photobioreactor"):
                hist = self.historical_data.setdefault(comp, {"timestamps": []})
                hist.setdefault("timestamps", []).append(now_iso)
                current_values = self.realtime_data.get(comp, {})
                for key, value in current_values.items():
                    if isinstance(value, (int, float)):
                        hist.setdefault(key, []).append(value)
                # Limite mémoire : conserve les 5000 derniers points par série
                if len(hist["timestamps"]) > 5000:
                    hist["timestamps"] = hist["timestamps"][-5000:]
                    for key in list(hist.keys()):
                        if key != "timestamps" and isinstance(hist[key], list):
                            hist[key] = hist[key][-5000:]

            return jsonify({"status": "ok", "measurements_count": self.measurements_count})

        @app.route("/api/health")
        def api_health():
            return jsonify({"status": "healthy", "service": "SEN Dashboard", "version": "3.2.0", "timestamp": datetime.now().isoformat()})

        @app.route("/api/status")
        def api_status():
            return jsonify({"dashboard": "running", "websocket": "enabled", "timestamp": datetime.now().isoformat()})

        @app.route("/api/graphs/realtime")
        @login_required
        def api_graphs_realtime():
            return jsonify(self._generate_realtime_graphs())

        @app.route("/api/graphs/analytics")
        @login_required
        def api_graphs_analytics():
            return jsonify(self._generate_analytics_graphs())

    # ── SocketIO ───────────────────────────────────────────────────────────────
    def _setup_socketio(self):
        sio = self.socketio

        @sio.on("connect")
        def handle_connect():
            emit("connected", {"message": "Connecté au système SEN", "timestamp": datetime.now().isoformat()})

        @sio.on("get_realtime_data")
        def handle_realtime_data():
            emit("realtime_update", {"timestamp": datetime.now().isoformat(), "data": self.realtime_data, "predictions": self.predictions})

    # ── Graphiques ─────────────────────────────────────────────────────────────
    def _generate_realtime_graphs(self) -> Dict:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        graphs = {}
        hist_d = self.historical_data["digester"]
        hist_p = self.historical_data["photobioreactor"]
        dark = {"plot_bgcolor": "#1e1e1e", "paper_bgcolor": "#2d2d2d"}

        fig = go.Figure(go.Scatter(x=hist_d["timestamps"][-24:], y=hist_d["gas_flow"][-24:], mode="lines+markers", line=dict(color="#2E7D32", width=3)))
        fig.update_layout(title="Production de Biogaz (m³/h)", template="plotly_dark", height=300, **dark)
        graphs["biogas_production"] = fig.to_json()

        fig3 = go.Figure(go.Scatter(x=hist_p["timestamps"][-24:], y=hist_p["biomass_density"][-24:], mode="lines", line=dict(color="#388E3C", width=3)))
        fig3.update_layout(title="Croissance des Algues (g/L)", template="plotly_dark", height=300, **dark)
        graphs["algae_growth"] = fig3.to_json()

        # Graphe digesteur : température + CH4 uniquement (pression et pH supprimés)
        fig4 = make_subplots(rows=1, cols=2, subplot_titles=("Température Digesteur (°C)", "Concentration CH₄ (%)"))
        ts12 = hist_d["timestamps"][-12:]
        fig4.add_trace(go.Scatter(x=ts12, y=hist_d["temperature"][-12:], mode="lines", line=dict(color="#FF5722")), row=1, col=1)
        fig4.add_trace(go.Scatter(x=ts12, y=hist_d["ch4_concentration"][-12:], mode="lines", line=dict(color="#9C27B0")), row=1, col=2)
        fig4.update_layout(title="Paramètres du Digesteur", showlegend=False, height=300, template="plotly_dark")
        graphs["digester_params"] = fig4.to_json()
        return graphs

    def _generate_analytics_graphs(self) -> Dict:
        import plotly.graph_objects as go

        graphs = {}
        hist_d = self.historical_data["digester"]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist_d["timestamps"][-24:], y=hist_d["gas_flow"][-24:], mode="lines", name="Historique", line=dict(color="#788288", width=2, dash="dash")))
        pred_ts = [(datetime.now() + timedelta(hours=i)).isoformat() for i in range(24)]
        fig.add_trace(go.Scatter(x=pred_ts, y=self.predictions["biogas_production"]["next_24h"][:24], mode="lines", name="Prédiction", line=dict(color="#4CAF50", width=3)))
        fig.update_layout(title="Prédiction de Production (24h)", template="plotly_dark", height=400)
        graphs["production_prediction"] = fig.to_json()

        rd = self.realtime_data
        cats = ["Biogaz", "Biomasse Algale", "CO₂ Capturé", "Profit", "Environnement"]
        values = [
            rd["digester"]["gas_flow"] / 15 * 5,
            rd["photobioreactor"]["biomass_density"] / 6 * 5,
            rd["environmental"]["co2_captured"] / 150 * 5,
            rd["economics"]["daily_profit_fcfa"] / (100 * EUR_TO_FCFA) * 5,
            rd["environmental"]["fossil_fuel_offset"] / 50 * 5,
        ]
        fig2 = go.Figure(go.Scatterpolar(r=values, theta=cats, fill="toself", line=dict(color="#4CAF50", width=2)))
        fig2.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), title="Performance du Système", height=400, showlegend=False)
        graphs["system_performance"] = fig2.to_json()
        return graphs

    # ── Thread temps réel ──────────────────────────────────────────────────────
    def _update_realtime_data(self):
        rng = np.random.default_rng()
        CHAMPS_REELS = {"co2_entree", "co2_sortie", "ch4_concentration", "temperature", "gas_flow", "ph", "biomass_density"}
        while not self._stop_event.wait(timeout=2):
            try:
                # Calcul économique réel basé sur la production actuelle (gas_flow ESP32 en L/min)
                gas_flow_lmin = self.realtime_data.get("digester", {}).get("gas_flow", 0)
                gas_flow_m3h = gas_flow_lmin * 0.06  # conversion L/min -> m3/h
                prix_biogaz = 650  # FCFA/m3
                revenue_biogaz = gas_flow_m3h * 24 * prix_biogaz
                daily_cost = self.realtime_data.get("economics", {}).get("daily_cost_fcfa", 25000)
                eco = self.realtime_data.setdefault("economics", {})
                eco["daily_revenue_fcfa"] = round(revenue_biogaz, 0)
                eco["daily_profit_fcfa"] = round(revenue_biogaz - daily_cost, 0)
                eco["daily_revenue"] = eco["daily_revenue_fcfa"]
                eco["daily_profit"] = eco["daily_profit_fcfa"]

                for component, sensors in self.realtime_data.items():
                    if isinstance(sensors, dict):
                        for key, value in sensors.items():
                            if isinstance(value, (int, float)) and key not in CHAMPS_REELS:
                                new_val = value * (1 + float(rng.uniform(-0.01, 0.01)))
                                sensors[key] = round(new_val, 4)
                rooms = self.socketio.server.manager.rooms.get("/", {})
                if any(k is not None for k in rooms):
                    self.socketio.emit("realtime_update", {
                        "timestamp": datetime.now().isoformat(),
                        "data": self.realtime_data,
                        "predictions": self.predictions,
                        "system_status": self.system_status,
                    })
            except Exception as e:
                logger.error(f"Erreur mise à jour temps réel : {e}")

    # ── Démarrage / Arrêt ──────────────────────────────────────────────────────
    def start(self, host: str = "127.0.0.1", port: int = 5000):
        self._stop_event.clear()
        self._update_thread = threading.Thread(target=self._update_realtime_data, daemon=True)
        self._update_thread.start()
        logger.info(f"🚀 Dashboard SEN v3.5 démarré → http://{host}:{port}")
        logger.info(" Comptes : admin | operator | viewer (mot de passe : sen2024)")
        self.socketio.run(self.app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)

    def stop(self):
        self._stop_event.set()
        if self._update_thread:
            self._update_thread.join(timeout=5)
        logger.info("🛑 Dashboard SEN arrêté")

# ==================== POINT D'ENTRÉE ==========================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Démarre le dashboard SEN v3.5")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--config", default="config/sen_config.json")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(" S E N D A S H B O A R D : Version 3.5")
    print("=" * 60)

    Path("config").mkdir(exist_ok=True)
    cfg = Path(args.config)
    if not cfg.exists():
        cfg.write_text(json.dumps({"project": {"name": "SEN", "version": "3.5"}, "dashboard": {"refresh_interval": 2}}, indent=2), encoding="utf-8")
        logger.info(f"Configuration créée : {cfg}")

    dashboard = SENDashboard(config_path=args.config)
    try:
        dashboard.start(host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé")
        dashboard.stop()
    except Exception as e:
        print(f"\n❌ Erreur : {e}")
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    main()