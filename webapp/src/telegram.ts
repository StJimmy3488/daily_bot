// The bits of the Telegram Mini App SDK (telegram-web-app.js) this app uses.
interface TelegramWebApp {
  initData: string;
  colorScheme: "light" | "dark";
  ready(): void;
  expand(): void;
  showConfirm(message: string, callback: (ok: boolean) => void): void;
  HapticFeedback: {
    impactOccurred(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
    selectionChanged(): void;
  };
  BackButton: {
    show(): void;
    hide(): void;
    onClick(cb: () => void): void;
    offClick(cb: () => void): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

// Outside Telegram (browser dev) initData is empty and these become no-ops.
export const tg: TelegramWebApp | undefined = window.Telegram?.WebApp?.initData ? window.Telegram.WebApp : undefined;

export const initData: string = tg?.initData || import.meta.env.VITE_DEV_INIT_DATA || "";

export const haptic = {
  tap: () => tg?.HapticFeedback.impactOccurred("light"),
  success: () => tg?.HapticFeedback.notificationOccurred("success"),
  error: () => tg?.HapticFeedback.notificationOccurred("error"),
  select: () => tg?.HapticFeedback.selectionChanged(),
};

export function confirm(message: string): Promise<boolean> {
  if (tg) return new Promise((resolve) => tg!.showConfirm(message, resolve));
  return Promise.resolve(window.confirm(message));
}

/** Show Telegram's back button while `active`; returns a cleanup function. */
export function useBackButton(onBack: () => void): () => void {
  if (!tg) return () => {};
  tg.BackButton.onClick(onBack);
  tg.BackButton.show();
  return () => {
    tg!.BackButton.offClick(onBack);
    tg!.BackButton.hide();
  };
}
