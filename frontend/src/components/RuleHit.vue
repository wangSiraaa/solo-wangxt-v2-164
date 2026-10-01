<script setup>
defineProps({ hit: Object })
</script>

<template>
  <div class="rule-hit" :class="hit.passed ? 'pass' : 'fail'">
    <div class="row" style="justify-content: space-between">
      <span>
        <span class="badge" :class="hit.passed ? 'ok' : 'bad'">
          {{ hit.passed ? '命中通过' : '命中失败' }}
        </span>
        <b style="margin-left: 8px">{{ hit.code }}</b>
        <span class="muted" style="margin-left: 6px">{{ hit.description }}</span>
      </span>
      <span class="badge info">
        {{ hit.fare_code }} · 规则版本 v{{ hit.version_number }}
        <span class="muted">(#{{ hit.version_id }})</span>
      </span>
    </div>
    <div class="expr" style="margin-top: 5px">表达式：{{ hit.expression }}</div>
    <div v-if="hit.component_segments" class="small muted">
      作用运价组件覆盖航段：#{{ hit.component_segments.map(i => i + 1).join('、#') }}
    </div>
    <div v-if="hit.error" class="error-box small">{{ hit.error }}</div>
  </div>
</template>
