/// <reference types="vite/client" />

declare module '*.css' {
  const content: string;
  export default content;
}

declare module '*.json' {
  const value: Record<string, unknown>;
  export default value;
}

declare module '*.svg' {
  const content: string;
  export default content;
}
