<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <section class="space-y-3">
    <div>
      <h2 class="text-base font-semibold">{{ title }}</h2>
      <p v-if="subtitle" class="text-xs text-muted-foreground">{{ subtitle }}</p>
    </div>
    <slot />
  </section>
</template>
