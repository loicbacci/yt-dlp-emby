type NavigateFn = (url: string, options?: { replace?: boolean }) => void;

let navigate: NavigateFn | null = null;
let pending: string[] = [];

export function setNavigator(fn: NavigateFn | null) {
  navigate = fn;
  if (fn && pending.length) {
    const urls = pending;
    pending = [];
    for (const url of urls) fn(url);
  }
}

export function go(url: string, options?: { replace?: boolean }) {
  if (navigate) {
    navigate(url, options);
    return;
  }
  pending.push(url);
}
