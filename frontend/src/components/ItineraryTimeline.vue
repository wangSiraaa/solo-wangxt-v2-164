<script setup>
import { computed } from 'vue'

const props = defineProps({
  segments: { type: Array, required: true },
  junctions: { type: Array, default: () => [] },
})

// 把航段和接续点交错成一条时间线：[段0] -接续- [段1] -接续- ...
const chain = computed(() => {
  const items = []
  props.segments.forEach((seg, i) => {
    items.push({ kind: 'segment', seg })
    const j = props.junctions.find((x) => x.between_segments[0] === i)
    if (j) items.push({ kind: 'junction', j })
  })
  return items
})
</script>

<template>
  <div class="timeline">
    <template v-for="(item, idx) in chain" :key="idx">
      <div v-if="item.kind === 'segment'" class="seg-card">
        <div class="row" style="justify-content: space-between">
          <b>{{ item.seg.flight }}</b>
          <span class="badge info">{{ item.seg.rbd }} · {{ item.seg.cabin_name }}</span>
        </div>
        <div style="margin-top: 6px">
          <div><b>{{ item.seg.dep_airport }}</b> 起飞 {{ item.seg.dep_local }}</div>
          <div class="muted small">UTC {{ item.seg.dep_utc.replace('T', ' ').slice(0, 16) }}</div>
        </div>
        <div style="margin-top: 6px">
          <div><b>{{ item.seg.arr_airport }}</b> 到达 {{ item.seg.arr_local }}</div>
          <div class="muted small">UTC {{ item.seg.arr_utc.replace('T', ' ').slice(0, 16) }}</div>
        </div>
        <div class="small muted" style="margin-top: 4px">余位 {{ item.seg.seats }}</div>
      </div>

      <div v-else class="seg-link">
        <span
          class="badge"
          :class="item.j.kind === 'TRANSFER' ? 'info'
            : item.j.kind === 'STOPOVER' ? 'warn' : 'ok'"
        >
          {{ item.j.kind === 'TRANSFER' ? '转机'
            : item.j.kind === 'STOPOVER' ? '中途停留' : '折返停留' }}
          {{ item.j.gap_hours }}h
        </span>
        <div class="line" style="margin: 6px 0"></div>
        <div class="small" style="text-align: center">
          <div>{{ item.j.airport }} 当地日历</div>
          <div :class="item.j.local_calendar_diff_days !== item.j.utc_date_diff_days ? 'warn' : 'muted'">
            {{ item.j.arr_local_date }} → {{ item.j.dep_local_date }}
            = <b>{{ item.j.local_calendar_diff_days }}</b> 日
          </div>
          <div v-if="item.j.local_calendar_diff_days !== item.j.utc_date_diff_days" class="small">
            ⚠ 若按 UTC 裸日期算是 {{ item.j.utc_date_diff_days }} 日 —— 不能那样算
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
