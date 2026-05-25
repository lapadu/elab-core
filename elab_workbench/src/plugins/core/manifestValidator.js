/**
 * Manifest validation for plugin-side and incoming-provider manifests.
 *
 * Loads the canonical JSON schema shipped under `schemas/ManifestSchema.json`
 * and exposes a single `validateManifest(manifest)` function.
 *
 * Goals:
 *  - Reject obviously malformed manifests in the workbench *before* a
 *    plugin renders, so a buggy or hostile provider cannot crash the UI.
 *  - Provide a clear list of errors for logging and the optional
 *    "schema violation" fallback widget.
 */
import Ajv from 'ajv'
import addFormats from 'ajv-formats'
// Vite resolves JSON imports natively.
import manifestSchema from '../../../../schemas/ManifestSchema.json'

const ajv = new Ajv({ allErrors: true, strict: false })
addFormats(ajv)

let _compiled = null
function _validator() {
    if (_compiled) return _compiled
    try {
        _compiled = ajv.compile(manifestSchema)
    } catch (err) {
        // Schema bug: log loud, but do not crash the app.
        console.error('🚨 Failed to compile ManifestSchema:', err)
        // Always-pass fallback so the UI keeps working.
        _compiled = () => true
        _compiled.errors = null
    }
    return _compiled
}

/**
 * Validate a manifest against the JSON schema.
 *
 * @param {object} manifest
 * @returns {{ ok: boolean, errors: import('ajv').ErrorObject[] | null }}
 */
export function validateManifest(manifest) {
    const validate = _validator()
    const ok = validate(manifest)
    return { ok, errors: ok ? null : validate.errors || [] }
}

/** Format Ajv errors into a short human-readable string. */
export function formatManifestErrors(errors) {
    if (!errors || !errors.length) return ''
    return errors
        .slice(0, 5)
        .map((e) => `${e.instancePath || '/'} ${e.message}`)
        .join('; ')
}
