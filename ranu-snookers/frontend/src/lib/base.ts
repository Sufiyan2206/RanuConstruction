/** Turns "/tables/x.svg" or "/#games" into a URL that works wherever the app is mounted (e.g. /snookers/). */
export const withBase = (path: string): string => import.meta.env.BASE_URL + path.replace(/^\//, "");
