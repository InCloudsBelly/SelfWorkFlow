#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FROZEN_UPSTREAM_COMMIT } from "./materialize-openwiki.mjs";
import { updateCompatibilityManifest } from "./update-upstream.mjs";

const moduleRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
updateCompatibilityManifest(moduleRoot, path.join(moduleRoot, ".work/openwiki"), FROZEN_UPSTREAM_COMMIT);
process.stdout.write("Wiki compatibility binding refreshed; capability verification is still required.\n");
