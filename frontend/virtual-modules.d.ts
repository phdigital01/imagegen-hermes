/** Build-time stylesheet module, embedded in the distributed ESM entry. */
declare module 'imagegen:styles' {
  const css: string
  export default css
}

/** Build-time picker thumbnails (`frontend/assets/thumbs`), keyed by name without extension. */
declare module 'imagegen:thumbs' {
  const thumbs: Record<string, string>
  export default thumbs
}
