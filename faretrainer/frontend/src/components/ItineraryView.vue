<script setup>
defineProps({
  segments: { type: Array, default: () => [] },
  transits: { type: Array, default: () => [] },
})
</script>

<template>
  <div>
    <template v-for="(seg, i) in segments" :key="i">
      <div class="seg-row">
        <div class="seg-line">
          段{{ i + 1 }} · {{ seg.flight }}
          <span
            class="badge"
            :class="seg.available ? 'ok' : 'fail'"
          >{{ seg.booking_class }} {{ seg.available ? '可售' : '不可用' }}</span>
        </div>
        <div class="seg-times">
          <div>
            <b>{{ seg.from }}</b> → <b>{{ seg.to }}</b>
          </div>
          <div class="seg-local">
            当地 {{ seg.dep_local }} 起 / {{ seg.arr_local }} 到
          </div>
          <div class="utc">
            UTC {{ seg.dep_utc.replace('T', ' ').slice(0, 16) }} →
            {{ seg.arr_utc.replace('T', ' ').slice(0, 16) }}
          </div>
        </div>
      </div>
      <div
        v-if="transits[i]"
        class="transit"
        :class="{ stopover: transits[i].kind === '停留' }"
      >
        {{ transits[i].kind }}于 {{ transits[i].airport }}，
        衔接 {{ transits[i].minutes }} 分钟
        <template v-if="transits[i].minutes >= 1440">
          （≥24h 计为停留，非转机）
        </template>
        <span v-if="transits[i].date_changed_local" class="badge warn">
          跨过机场本地日期
        </span>
        <span class="muted small">
          （分钟数由 UTC 时间差计算；跨日按 {{ transits[i].airport }}
          本地日历判定，非日期字符串相减）
        </span>
      </div>
    </template>
  </div>
</template>
