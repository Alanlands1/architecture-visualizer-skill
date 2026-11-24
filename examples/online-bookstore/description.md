# PageTurn Online Bookstore: how our system works

This is the kind of input the skill expects: a description in plain English, written the way you would explain the system to a new teammate. No diagrams, no architecture terms.

## Who uses it

We run an online bookstore called PageTurn. Shoppers browse and buy books on our website. There is also a mobile app that does the same thing. Our store managers do not use the shop itself; they use a separate Admin Dashboard.

The website, the mobile app and the Admin Dashboard all talk to one backend that we call the Store API. They talk to it over HTTPS.

## Signing in

Shoppers sign in with their Google account. The Store API checks each sign-in with Google.

## Browsing and searching

The Store API looks up books in the Catalog Database. The most popular books are also kept in a Redis cache, which we call the Book Cache, so the Store API checks there first.

When a shopper types something in the search box, the Store API asks the Search Service, because it is much quicker at finding books than the database. Every night a Catalog Sync Job reads all the books from the Catalog Database and copies them into the Search Service, so search results are at most one day old.

## Checkout

When a shopper checks out, three things happen in this order:

1. The Store API asks the Inventory Service whether the books are in stock. The Inventory Service keeps stock numbers in its own Inventory Database.
2. The Store API saves the order.
3. The Store API asks the Payment Service to take the money. The Payment Service uses Stripe to charge the card.

If the payment fails, the shopper sees an error and nothing else happens.

## After the payment

Once the payment has worked, the Store API puts a message on the Order Queue. Three things listen to that queue:

- The Shipping Service picks up the order and books a delivery with our courier, DHL. Later, DHL sends delivery updates back to the Shipping Service.
- The Email Service sends the shopper a confirmation email through SendGrid.
- The Inventory Service lowers the stock numbers for the books that were sold.

## Reports and managing the shop

Every night a Sales Report Job reads the day's orders and puts a summary file in the Reports Folder.

Store managers open the Admin Dashboard to see those reports; the dashboard reads them straight from the Reports Folder. Managers also use the dashboard to add new books. The dashboard sends new books to the Store API, which saves them in the Catalog Database.
