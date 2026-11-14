// Shared company business roles; custom values remain editable.
window.TophooCompanyTypes = {
  labels: {distributor:'经销商',importer:'进口商',wholesaler:'批发商',retailer:'零售商',manufacturer:'制造商',contractor:'工程承包商',supplier:'供应商',end_user:'终端用户',service_provider:'服务商'},
  label(value) { return this.labels[value] || value || '未知'; },
  suggestions() { return Object.entries(this.labels).map(([value,label])=>`<option value="${value}">${label}</option>`).join(''); }
};
