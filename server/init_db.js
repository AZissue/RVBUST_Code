const db = require('./database');

(async () => {
  try {
    await db.init();
    console.log('After init, data keys:', db.data ? Object.keys(db.data) : 'undefined');
    await db.seedData();
    console.log('DB seeded, users:', db.data.users.length, 'customers:', db.data.customers.length, 'tickets:', db.data.tickets.length);
  } catch (e) {
    console.error('Error:', e.message);
    process.exit(1);
  }
})();
