import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig(({ mode }) => {
  void mode;

  function spaHistoryFallbackPlugin() {
    return {
      name: 'spa-history-fallback',
      configureServer(server: {
        middlewares: {
          use: (middleware: (req: Req, res: Res, next: NextFn) => void) => void;
        };
      }) {
        server.middlewares.use((req: Req, res: Res, next: NextFn) => {
          const url = req.url || '';
          // SPA 单入口:任何非 /api、非静态资源(带扩展名)、非 vite 内部路径的
          // 干净 URL(/platform、/console、/console#... 等)都回退到 index.html,
          // 由 main.tsx 的 React Router 接管。带扩展名的请求(.html/.svg/.js/.css)
          // 已被 /\.\w+/ 放行,直接交给 vite 静态处理。
          if (
            url.startsWith('/api') ||
            url.startsWith('/assets/') ||
            url.startsWith('/@') ||
            url.startsWith('/node_modules/') ||
            /\.\w+(\?|$)/.test(url)
          ) {
            return next();
          }
          req.url = '/index.html';
          next();
        });
      },
    };
  }

  return {
    plugins: [react({ jsxRuntime: 'classic' }), spaHistoryFallbackPlugin()],

    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },

    optimizeDeps: {
      include: [
        'react',
        'react-dom',
        'react-dom/client',
        '@cloudscape-design/global-styles',
        '@cloudscape-design/components/theming',
        '@cloudscape-design/components/alert',
        '@cloudscape-design/components/app-layout',
        '@cloudscape-design/components/badge',
        '@cloudscape-design/components/box',
        '@cloudscape-design/components/button',
        '@cloudscape-design/components/button-dropdown',
        '@cloudscape-design/components/cards',
        '@cloudscape-design/components/column-layout',
        '@cloudscape-design/components/container',
        '@cloudscape-design/components/expandable-section',
        '@cloudscape-design/components/file-upload',
        '@cloudscape-design/components/form-field',
        '@cloudscape-design/components/header',
        '@cloudscape-design/components/input',
        '@cloudscape-design/components/key-value-pairs',
        '@cloudscape-design/components/modal',
        '@cloudscape-design/components/progress-bar',
        '@cloudscape-design/components/segmented-control',
        '@cloudscape-design/components/select',
        '@cloudscape-design/components/side-navigation',
        '@cloudscape-design/components/space-between',
        '@cloudscape-design/components/split-panel',
        '@cloudscape-design/components/status-indicator',
        '@cloudscape-design/components/table',
        '@cloudscape-design/components/tabs',
        '@cloudscape-design/components/text-filter',
        '@cloudscape-design/components/textarea',
        '@cloudscape-design/components/toggle',
        '@cloudscape-design/components/top-navigation',
        '@cloudscape-design/components/wizard',
      ],
    },

    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:7860',
          changeOrigin: true,
        },
      },
    },

    preview: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:7860',
          changeOrigin: true,
        },
      },
    },

    build: {
      cssCodeSplit: true,
      reportCompressedSize: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          assetFileNames: 'assets/[name]-[hash][extname]',
          chunkFileNames: 'assets/[name]-[hash].js',
          entryFileNames: 'assets/[name]-[hash].js',
          manualChunks: (id: string) => {
            if (
              id.includes('node_modules/react/') ||
              id.includes('node_modules/react-dom/') ||
              id.includes('node_modules/scheduler/') ||
              id.includes('node_modules/react-router') ||
              id.includes('node_modules/@remix-run/')
            ) {
              return 'react-vendor';
            }
            if (id.includes('node_modules/@cloudscape-design/')) {
              return 'cloudscape';
            }
            if (id.includes('node_modules/i18next') || id.includes('node_modules/react-i18next')) {
              return 'i18n';
            }
            if (id.includes('node_modules/ace-builds')) {
              return 'ace-editor';
            }
            if (id.includes('/features/scripts/script-edit-')) {
              return 'script-editors';
            }
            return undefined;
          },
        },
      },
    },
  };
});

// ── Inline types for connect middleware ─────────────────
interface Req {
  url?: string;
}

interface Res {
  // minimal response interface
}

type NextFn = () => void;
