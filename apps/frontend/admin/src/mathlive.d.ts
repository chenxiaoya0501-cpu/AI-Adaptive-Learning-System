import type { MathfieldElement } from 'mathlive'

declare global {
  namespace JSX {
    interface IntrinsicElements {
      'math-field': React.DetailedHTMLProps<
        React.HTMLAttributes<MathfieldElement> & {
          value?: string
          children?: React.ReactNode
          'virtual-keyboard-mode'?: 'manual' | 'onfocus' | 'off'
        },
        MathfieldElement
      >
    }
  }
}

export {}
