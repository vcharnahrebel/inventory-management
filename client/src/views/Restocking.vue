<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>

      <!-- Success banner -->
      <div v-if="successMessage" class="success-banner">
        <div class="success-message">{{ successMessage }}</div>
        <button class="btn-link" @click="router.push('/orders')">
          {{ t('restocking.viewInOrders') }}
        </button>
      </div>

      <!-- Budget slider card -->
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
          <span class="budget-display">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
        </div>
        <div class="slider-wrapper">
          <span class="slider-label">{{ currencySymbol }}0</span>
          <input
            type="range"
            min="0"
            max="500000"
            step="5000"
            v-model.number="budget"
            class="budget-slider"
          />
          <span class="slider-label">{{ currencySymbol }}500K</span>
        </div>
      </div>

      <!-- Summary stats -->
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.itemsSelected') }}</div>
          <div class="stat-value">{{ selectedCount }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ totalCost.toLocaleString() }}</div>
        </div>
        <div :class="['stat-card', budgetRemaining < 0 ? 'danger' : 'warning']">
          <div class="stat-label">{{ t('restocking.budgetRemaining') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ budgetRemaining.toLocaleString() }}</div>
        </div>
      </div>

      <!-- No recommendations at all -->
      <div v-if="recommendations.length === 0" class="empty-state">
        {{ t('restocking.noRecommendations') }}
      </div>

      <div v-else>
        <!-- No items fit the budget -->
        <div v-if="selectedCount === 0" class="info-notice">
          {{ t('restocking.noItems') }}
        </div>

        <!-- Recommendations table -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
            <button
              class="btn-primary"
              :disabled="selectedCount === 0 || submitting"
              @click="placeOrder"
            >
              {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
            </button>
          </div>

          <div class="table-container">
            <table class="restocking-table">
              <thead>
                <tr>
                  <th class="col-item">{{ t('restocking.table.item') }}</th>
                  <th class="col-trend">{{ t('restocking.table.trend') }}</th>
                  <th class="col-qty">{{ t('restocking.table.quantity') }}</th>
                  <th class="col-unit">{{ t('restocking.table.unitCost') }}</th>
                  <th class="col-line">{{ t('restocking.table.lineCost') }}</th>
                  <th class="col-lead">{{ t('restocking.table.leadTime') }}</th>
                  <th class="col-status">{{ t('restocking.table.status') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in annotatedRecommendations"
                  :key="item.item_sku"
                  :class="{ 'row-excluded': !item.included }"
                >
                  <td class="col-item">
                    <div class="item-cell">
                      <strong>{{ translateProductName(item.item_name) }}</strong>
                      <span class="item-sku">{{ item.item_sku }}</span>
                    </div>
                  </td>
                  <td class="col-trend">
                    <span :class="['badge', getTrendBadgeClass(item.trend)]">
                      {{ t(`restocking.trend.${item.trend}`) }}
                    </span>
                  </td>
                  <td class="col-qty">{{ item.recommended_quantity }}</td>
                  <td class="col-unit">{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                  <td class="col-line">
                    <strong>{{ currencySymbol }}{{ item.estimated_cost.toLocaleString() }}</strong>
                  </td>
                  <td class="col-lead">{{ t('orders.leadTimeDays', { days: item.lead_time_days }) }}</td>
                  <td class="col-status">
                    <span :class="['badge', item.included ? 'success' : 'neutral']">
                      {{ item.included ? t('restocking.included') : t('restocking.excluded') }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()
    const router = useRouter()

    const currencySymbol = computed(() => currentCurrency.value === 'JPY' ? '¥' : '$')

    // --- State ---
    const budget = ref(100000)
    const recommendations = ref([])
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref(null)
    const submittedOrderNumber = ref(null)

    // --- Load recommendations ---
    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        recommendations.value = await api.getRestockingRecommendations()
      } catch (err) {
        error.value = 'Failed to load restocking recommendations: ' + err.message
        console.error(err)
      } finally {
        loading.value = false
      }
    }

    onMounted(loadRecommendations)

    // --- Greedy selection (CRITICAL LOGIC):
    //   The API returns items already sorted in priority order.
    //   We walk the list in that order, maintaining a running total.
    //   An item is INCLUDED if its estimated_cost fits within the remaining budget.
    //   We STOP at the first item that does NOT fit — we do NOT skip ahead to
    //   potentially cheaper later items. This is a greedy knapsack approximation
    //   that respects the pre-computed priority ranking from the backend.
    const annotatedRecommendations = computed(() => {
      let remaining = budget.value
      let stopped = false

      return recommendations.value.map(item => {
        if (stopped || item.estimated_cost > remaining) {
          stopped = true
          return { ...item, included: false }
        }
        remaining -= item.estimated_cost
        return { ...item, included: true }
      })
    })

    // Included items only
    const includedItems = computed(() =>
      annotatedRecommendations.value.filter(i => i.included)
    )

    const selectedCount = computed(() => includedItems.value.length)

    const totalCost = computed(() =>
      includedItems.value.reduce((sum, i) => sum + i.estimated_cost, 0)
    )

    const budgetRemaining = computed(() => budget.value - totalCost.value)

    // --- Trend badge class ---
    const getTrendBadgeClass = (trend) => {
      const map = {
        increasing: 'increasing',
        stable: 'stable',
        decreasing: 'decreasing'
      }
      return map[trend] || 'info'
    }

    // --- Place order ---
    const placeOrder = async () => {
      if (selectedCount.value === 0 || submitting.value) return

      submitting.value = true
      error.value = null

      try {
        const orderData = {
          items: includedItems.value.map(i => ({
            sku: i.item_sku,
            name: i.item_name,
            quantity: i.recommended_quantity,
            unit_price: i.unit_cost,
            lead_time_days: i.lead_time_days
          })),
          budget: budget.value
        }

        const created = await api.createRestockingOrder(orderData)
        submittedOrderNumber.value = created.order_number
        successMessage.value = t('restocking.orderSuccess', { orderNumber: created.order_number })
      } catch (err) {
        error.value = 'Failed to place restocking order: ' + err.message
        console.error(err)
      } finally {
        submitting.value = false
      }
    }

    return {
      t,
      currencySymbol,
      translateProductName,
      router,
      // state
      budget,
      recommendations,
      loading,
      error,
      submitting,
      successMessage,
      submittedOrderNumber,
      // computed
      annotatedRecommendations,
      selectedCount,
      totalCost,
      budgetRemaining,
      // methods
      getTrendBadgeClass,
      placeOrder
    }
  }
}
</script>

<style scoped>
/* Budget card */
.budget-card .card-header {
  align-items: center;
}

.budget-display {
  font-size: 1.75rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.slider-wrapper {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding-top: 0.5rem;
}

.slider-label {
  font-size: 0.813rem;
  color: #64748b;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.budget-slider {
  flex: 1;
  height: 6px;
  appearance: none;
  -webkit-appearance: none;
  background: #e2e8f0;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  accent-color: #3b82f6;
}

.budget-slider::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(59, 130, 246, 0.4);
  transition: box-shadow 0.15s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  box-shadow: 0 1px 8px rgba(59, 130, 246, 0.6);
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(59, 130, 246, 0.4);
}

/* Success banner */
.success-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
}

.success-message {
  font-size: 0.938rem;
  font-weight: 500;
  color: #065f46;
}

.btn-link {
  background: none;
  border: none;
  color: #2563eb;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  text-decoration: underline;
  padding: 0;
  flex-shrink: 0;
}

.btn-link:hover {
  color: #1d4ed8;
}

/* Primary button */
.btn-primary {
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 1.25rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, opacity 0.15s ease;
  white-space: nowrap;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Empty / notice states */
.empty-state {
  text-align: center;
  padding: 3rem;
  color: #64748b;
  font-size: 0.938rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  margin-bottom: 1.25rem;
}

.info-notice {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  padding: 0.875rem 1rem;
  border-radius: 8px;
  font-size: 0.938rem;
  margin-bottom: 1.25rem;
}

/* Table */
.restocking-table {
  table-layout: fixed;
  width: 100%;
}

.col-item   { width: 220px; }
.col-trend  { width: 110px; }
.col-qty    { width: 90px; }
.col-unit   { width: 110px; }
.col-line   { width: 110px; }
.col-lead   { width: 130px; }
.col-status { width: 110px; }

.item-cell {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.item-sku {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 400;
}

/* Excluded rows are dimmed */
.row-excluded {
  opacity: 0.45;
}

/* Neutral badge for excluded status */
.badge.neutral {
  background: #f1f5f9;
  color: #64748b;
}
</style>
