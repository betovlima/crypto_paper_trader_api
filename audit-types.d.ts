declare const __APP_VERSION__: string;
declare module "react" {
  export const StrictMode: any;
  export const useState: any;
  export const useEffect: any;
  export const useMemo: any;
  export const useCallback: any;
  export const useRef: any;
  export const useLayoutEffect: any;
  export const memo: any;
}
declare module "react-dom/client" { export const createRoot: any; }
declare module "react/jsx-runtime" { export const jsx: any; export const jsxs: any; export const Fragment: any; }
declare namespace JSX { interface IntrinsicElements { [elemName: string]: any; } }
interface ImportMetaEnv { readonly VITE_API_URL?: string; readonly DEV: boolean; }
interface ImportMeta { readonly env: ImportMetaEnv; }
