/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execSync } from 'node:child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const packageJsonPath = path.join(__dirname, 'package.json')
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'))

function getGitVersion() {
  try {
    // Get latest tag and compute next version
    const repoRoot = path.resolve(__dirname, '..')
    const tags = execSync(`git -C "${repoRoot}" tag --list`, { encoding: 'utf8' }).trim().split('\n').filter(Boolean)
    if (tags.length === 0) return '1.0.0'
    
    const lastTag = execSync(`git -C "${repoRoot}" tag --list --sort=-v:refname`, { encoding: 'utf8' }).trim().split('\n')[0]
    const match = lastTag.match(/^v?(\d+)\.(\d+)\.(\d+)$/)
    if (!match) return '1.0.0'
    
    const [, major, minor, patch] = match
    return `${major}.${minor}.${parseInt(patch) + 1}`
  } catch {
    console.warn('[vite] Warning: Could not determine git version, using fallback')
    return packageJson.version
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const envFile = loadEnv(mode, __dirname, '')
  let appVersion = globalThis.process?.env?.VITE_APP_VERSION
  
  if (!appVersion) {
    const nextVersion = getGitVersion()
    if (mode === 'development') {
      const suffix = envFile.VITE_APP_VERSION_SUFFIX || '-rc'
      appVersion = `${nextVersion}${suffix}`
    } else {
      // Production without explicit VITE_APP_VERSION: use git version with -rc
      appVersion = `${nextVersion}-rc`
    }
  }

  return {
    plugins: [react()],
    define: {
      APP_VERSION: JSON.stringify(appVersion),
    },
    build: {
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        output: {
          manualChunks: {
            // Split out the React runtime so it caches independently of app code.
            'react-vendor': ['react', 'react-dom'],
            // Socket.IO is large and stable -> separate chunk.
            'socket-vendor': ['socket.io-client'],
            // JSON-Schema validation runtime; only needed once the app boots.
            'ajv-vendor': ['ajv', 'ajv-formats'],
            // Icon library: heavy and tree-shake-resistant -> isolate it.
            'icons-vendor': ['lucide-react'],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
      setupFiles: ['./vitest.setup.js'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'lcov', 'json-summary'],
        reportsDirectory: './coverage',
      },
    },
  }
})
