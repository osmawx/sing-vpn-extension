export async function ensureCurrentBackground(e,n){const r=await e({type:"getVersion"});return!("unknown message type"===r.error||r.ok&&r.version!==n.getManifest().version)||(n.reload(),!1)}
