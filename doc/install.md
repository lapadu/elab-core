# E-Lab Project Setup Guide for VS Code

This guide describes how to set up the E-Lab Workbench locally with Visual Studio Code, React, and Tailwind CSS.

---

## 1. Install Prerequisites

Ensure that **Node.js** and **Python 3.9+** are installed on your computer.

- Node.js download: [nodejs.org](https://nodejs.org/) (LTS version recommended)
- Verify in the console: `node -v` and `npm -v`
- Python download: [python.org](https://www.python.org/) (3.9 – 3.13 recommended)
- Verify: `python --version` and `pip --version`

---

## 2. Create Frontend Project (with Vite)

Open your terminal and execute the following commands:

```bash
# Create a new project with the React template
npm create vite@latest elab_workbench -- --template react
```

> **Important notes on terminal prompts:**
>
> - If asked: `Need to install the following packages: create-vite@latest... Ok to proceed? (y)`, confirm with **y** and **Enter**.
>
> - If asked: **"Use rolldown-vite (Experimental)?"**, choose **No** to stay with the stable default version.
>
> - If asked: **"Install with npm and start now?"**, choose **No** (or cancel), as we will perform the installation manually in the next steps.

Continue with:

```bash
# Change into the folder
cd elab_workbench

# Install dependencies
npm install
```

---

## 3. Install Additional Frontend Libraries

The project requires `lucide-react` for icons and `tailwindcss` for styling.

```bash
# Install icons and Tailwind packages
npm install lucide-react
npm install -D tailwindcss postcss autoprefixer
```

---

## 4. Create Configuration Files (Manually)

Since the automatic command (`npx tailwindcss init`) often fails on newer Tailwind versions (v4) on Windows (`could not determine executable`), we create the configuration manually.

Create two new files in the main `elab_workbench` folder (next to `package.json`):

**File 1: `postcss.config.js`**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

**File 2: `tailwind.config.js`**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

---

## 5. Include CSS

Open `src/index.css` in VS Code and replace the **entire content** with the Tailwind directives:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* Optional global styles for scrollbars */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: #0f172a;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #334155;
  border-radius: 3px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #475569;
}
```

---

## 6. Insert the Application Code

1. Open `src/App.jsx`.
2. Delete all default content.
3. Paste the complete E-Lab Main code.
4. **Modularization (Recommended):** Split the code into separate files:
    - Create `src/utils/` with `Shared.jsx`.
    - Create `src/plugins/` with plugin files (`SignalGenerator.jsx`, `Voltmeter.jsx`, `Averager.jsx`, `CSVLogger.jsx`).
    - Use the version of `src/App.jsx` that imports these files.

---

## 7. Recommended VS Code Extensions

For the best development experience, install these extensions from the Marketplace (Ctrl+Shift+X):

- **ESLint** — Helps find errors in the code.
- **Prettier - Code formatter** — Formats your code automatically.
- **Tailwind CSS IntelliSense** — Provides autocompletion for Tailwind classes (very important!).
- **ES7+ React/Redux/React-Native snippets** — Useful shortcuts for React.

---

## 8. Start the Frontend

Run in the VS Code terminal:

```bash
npm run dev
```

Click the displayed link (usually `http://localhost:5173`) to open E-Lab in the browser.

---

## 9. Python Backend: Dependencies & Installation

Alle Python-Abhängigkeiten sind in [`requirements.txt`](../requirements.txt) im Projektstamm definiert.

### Installation mit Virtual Environment (empfohlen)

```bash
# Virtual Environment erstellen
python -m venv .venv

# Aktivieren
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### Installation prüfen

```bash
pip list | grep -E "flask|socketio|jsonschema|gevent"
```

---

## 10. Important Notes

1. **Python Version:** The project uses `async_mode='gevent'` for the Socket.IO server. Recommended versions: Python 3.9 to 3.13.

2. **Production Deployment:** For production use, see [`deployment.md`](deployment.md) which covers systemd, nginx/TLS, and session backup.

3. **Starting the Backend (Development):**

    ```bash
    python server.py
    ```

    The dispatcher starts on `http://localhost:5000` and broadcasts UDP discovery beacons on port 5005.

4. **Tests:** See [`test.md`](test.md) for test execution and coverage.
