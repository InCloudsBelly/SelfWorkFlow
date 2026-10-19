#!/usr/bin/env node

import { computePersonalToolBindings } from "../dist/personal-skill-adapter.js";
import { canonicalPersonalJson } from "../dist/personal-wiki-lifecycle.js";

process.stdout.write(
  `${canonicalPersonalJson(computePersonalToolBindings())}\n`,
);
