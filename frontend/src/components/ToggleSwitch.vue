<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: boolean
    disabled?: boolean
  }>(),
  { disabled: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'change', value: boolean): void
}>()

function toggle() {
  if (props.disabled) return
  const next = !props.modelValue
  emit('update:modelValue', next)
  emit('change', next)
}
</script>

<template>
  <button
    class="toggle-switch"
    :class="{ on: modelValue }"
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    @click="toggle"
  >
    <span class="toggle-thumb"></span>
  </button>
</template>

<style scoped>
.toggle-switch {
  position: relative;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: var(--border-strong);
  cursor: pointer;
  transition: background 0.18s ease;
}

.toggle-switch.on {
  background: var(--success);
}

.toggle-switch:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.18s ease;
}

.toggle-switch.on .toggle-thumb {
  transform: translateX(18px);
}

.toggle-switch:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
