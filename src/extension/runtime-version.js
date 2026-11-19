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

/** Bounds popup waiting while allowing the background's single update transaction to finish. */
export async function requestExtensionUpdate(send, request, timeoutMilliseconds = 120000) {
  let timeout;
  try {
    return await Promise.race([
      Promise.resolve().then(() => send(request)),
      new Promise((resolve) => {
        timeout = setTimeout(() => resolve({
          ok: false, timedOut: true,
          error: 'Update has not finished after two minutes. It may still be running. Reopen the extension to check the result.',
        }), timeoutMilliseconds);
      }),
    ]);
  } catch (error) {
    return { ok: false, error: error.message || 'Update failed. Reopen the extension and try again.' };
  } finally {
    clearTimeout(timeout);
  }
}
