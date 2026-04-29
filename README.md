# LogistiQ 🚀

**An AI-driven logistics optimization platform enabling real-time geospatial intelligence, autonomous rerouting, and predictive supply chain management.**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/react-%2320232a.svg?style=for-the-badge&logo=react&logoColor=%2361DAFB)](https://reactjs.org/)
[![Refine](https://img.shields.io/badge/Refine-141414?style=for-the-badge&logo=refine&logoColor=white)](https://refine.dev/)
[![TailwindCSS](https://img.shields.io/badge/tailwindcss-%2338B2AC.svg?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

---

## 🎯 The Problem & Solution

**The Bottleneck:** Modern supply chains and logistics networks in emerging markets face massive inefficiencies due to fragmented data, unforeseen geographical disruptions (floods, strikes, accidents), and reactive rather than proactive decision-making. 

**The LogistiQ Solution:** LogistiQ addresses these challenges head-on by aggregating multi-modal freight data and applying Agentic AI to monitor, predict, and autonomously respond to supply chain risks. By integrating real-time geospatial feeds with intelligent agent workflows, LogistiQ transforms a static tracking system into a dynamic, proactive control center that ensures operational resilience and optimal routing.

---

## ✨ Key Features

* **📡 Real-Time Fleet Tracking via WebSockets:** High-performance, low-latency live telemetry streams for tracking multi-modal shipments across the globe.
* **🧠 AI-Powered Route Optimization:** Integrates live environmental data to calculate and suggest the safest, fastest, and most cost-effective alternative routes on the fly.
* **🤖 Agentic AI & Autonomous Decision Making:** Background agents (Sentinel & Copilot) constantly monitor constraints and trigger automatic rerouting when critical risk thresholds are breached.
* **📦 Automated Inventory Management:** Smart tracking of warehouse and in-transit goods, ensuring tight synchronization between supply and demand.
* **🗺️ Geospatial Disruption Alerts:** PostGIS-powered spatial queries seamlessly flag shipments affected by dynamic real-world events like weather anomalies or traffic blockages.

---

## 🏗️ Tech Stack & Architecture

LogistiQ is engineered with a **Backend-First** approach and a highly robust API-centric design to ensure enterprise-grade stability and scalability.

* **Backend (FastAPI & PostGIS):** An asynchronous, high-throughput backend powered by Python's FastAPI. Uses PostgreSQL + PostGIS for complex spatial queries and Redis for caching and WebSockets pub/sub.
* **Frontend (Refine + React + Tailwind CSS):** We utilize **Refine** to rapidly build out a powerful, production-grade internal tooling interface that provides operators with a sophisticated dashboard, complete with dynamic mapping via deck.gl.
* **Agentic AI & MCP Integration:** The core brain of the platform uses background AI agents communicating through the **Model Context Protocol (MCP)**. This allows our models to seamlessly consume external APIs (like Open-Meteo or NASA FIRMS) to contextualize risk scores and independently propose routing adjustments.

---

## 📂 Project Structure

```text
logistiq-ai/
├── backend/                  # FastAPI Application
│   ├── agents/               # AI Agent workflows (Sentinel, Copilot, Decision)
│   ├── api/                  # RESTful routes and WebSockets endpoints
│   ├── core/                 # Config, security, middlewares, and logging
│   ├── db/                   # SQLAlchemy models, Alembic migrations, PostGIS setup
│   ├── mcp_servers/          # Model Context Protocol integrations (Weather, Routing, etc.)
│   ├── ml/                   # Machine learning models and risk scoring logic
│   └── main.py               # Application entry point
├── frontend/                 # Refine + React Frontend
│   ├── src/
│   │   ├── components/       # Reusable React components & Map overlays
│   │   ├── pages/            # View components & routing logic
│   │   ├── stores/           # Zustand state management
│   │   └── lib/              # API clients and utilities
│   ├── package.json
│   └── vite.config.ts
├── infra/                    # Infrastructure and deployment configurations
├── docs/                     # Additional project documentation
└── docker-compose.yml        # Multi-container orchestration (DB, Cache)
```

---

## ⚙️ Installation & Setup

### Prerequisites
* Docker & Docker Compose
* Node.js (v18+) & `pnpm`
* Python 3.11+ & [`uv`](https://github.com/astral-sh/uv) (Extremely fast Python package installer and resolver)

### 1. Infrastructure
Spin up the database (PostgreSQL + PostGIS) and caching (Redis) layers using Docker:
```bash
docker-compose up -d
```

### 2. Backend Setup
We manage our Python dependencies securely and quickly using **uv**.

```bash
# Navigate to backend directory
cd backend

# Install dependencies using uv
uv sync

# Copy example environment variables and configure them
cp .env.example .env

# Run the FastAPI server via uv
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend Setup
```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
pnpm install

# Configure environment variables
cp .env.example .env.local

# Start the Vite development server
pnpm run dev
```

### 🔑 Environment Variables
Do not hardcode credentials in your source files. Set the following in your respective `.env` files:

**Backend (`backend/.env`)**
```env
DATABASE_URL=postgresql+asyncpg://<USER>:<PASSWORD>@localhost:5432/<DB_NAME>
REDIS_URL=redis://localhost:6379
SECRET_KEY=<YOUR_SUPER_SECRET_JWT_KEY>
GEMINI_API_KEY=<YOUR_GOOGLE_GEMINI_KEY>
ENVIRONMENT=development
```

**Frontend (`frontend/.env.local`)**
```env
VITE_API_URL=http://localhost:8000/api/v1
VITE_WS_URL=ws://localhost:8000
VITE_STADIA_MAPS_API_KEY=<OPTIONAL_STADIA_KEY>
```

---

## 🚀 Future Roadmap

* **Blockchain Ledger:** Integrate a distributed ledger for immutable, smart-contract-based proof of delivery.
* **Predictive Fleet Maintenance:** Implement machine learning to predict when vehicles require maintenance based on IoT sensor data.
* **Advanced Multi-Modal Integrations:** Native drone routing API integrations for last-mile autonomous deliveries.
* **Mobile App:** A React Native companion app for drivers to streamline status updates and communicate directly with the AI Copilot.

---
_Built for the Google Solutions Challenge._
