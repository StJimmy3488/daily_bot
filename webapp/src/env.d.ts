/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

interface ImportMetaEnv {
  /** Signed init data for local dev in a normal browser: `uv run python -m bot.dev_init_data`. */
  readonly VITE_DEV_INIT_DATA?: string;
}
