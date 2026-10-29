/** Перезапускает расширение, если новый popup открылся со старым service worker. */
export async function ensureCurrentBackground(send, runtime) {
  const response = await send({ type: 'getVersion' });
  if (response.error === 'unknown message type'
      || (response.ok && response.version !== runtime.getManifest().version)) {
    runtime.reload();
    return false;
  }
  return true;
}
