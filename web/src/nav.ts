let navigate: ((url: string) => void) | null = null;
let pending: string | null = null;

export function setNavigator(fn: ((url: string) => void) | null) {
  navigate = fn;
  if (fn && pending) {
    const url = pending;
    pending = null;
    fn(url);
  }
}

export function go(url: string) {
  if (navigate) {
    navigate(url);
    return;
  }
  pending = url;
}
