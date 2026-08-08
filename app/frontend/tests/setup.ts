import { toHaveNoViolations } from 'jest-axe'
import { expect } from 'vitest'

// `jest-axe` ships its matcher in Jest's shape, which Vitest's `expect` accepts
// unchanged — this is the whole reason it works here without a Vitest-specific
// fork.
expect.extend(toHaveNoViolations)
