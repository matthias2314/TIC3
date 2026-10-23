<script setup>
import { useNav } from '@slidev/client'
const { currentPage, total } = useNav()
</script>
<template>
  <div v-if="currentPage !== 1" class="slide-footer">
    <span>{{ currentPage }} / {{ total }}</span>
  </div>
</template>
