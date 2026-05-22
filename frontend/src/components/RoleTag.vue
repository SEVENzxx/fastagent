<script setup lang="ts">
defineProps<{
  name: string
}>()
</script>

<template>
  <el-tag size="small" effect="plain" type="info">{{ name }}</el-tag>
</template>
